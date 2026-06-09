import gzip
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
from pyproj import Proj, transform
import rasterio
import xarray as xr

class LocalSpatialCimis:
    """完美融合 2km 官方 Spatial CIMIS 与 30m 个人高分 NetCDF 数据的科研级提取工具"""

    def __init__(self, data_root_dir: str):
        self.data_root = Path(data_root_dir)
        # 🎯 强力坐标转换管道
        self.wgs84 = Proj(init='epsg:4326')
        self.cal_albers = Proj(init='epsg:3310')

    def get_proj_xy(self, latitude: float, longitude: float):
        """精准、安全地将经纬度转换为加州 Albers 投影下的米制坐标 (X, Y)"""
        proj_x, proj_y = transform(self.wgs84, self.cal_albers, longitude, latitude)
        return proj_x, proj_y

    def load_corrected_raster(self, file_path: Path):
        """🎯 补齐该函数：内存解压并动态返回地图矩阵和精确的 Extent 边界"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_asc = Path(tmpdir) / file_path.stem
            with gzip.open(file_path, 'rb') as f_in:
                with open(target_asc, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            with rasterio.open(target_asc) as src:
                map_data = src.read(1)
                # 动态从 rasterio 内部提取边界
                bounds = src.bounds
                extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
                return map_data, extent, src

    def extract_point_value(self, file_path: Path, latitude: float, longitude: float) -> float:
        """动态解析官方 ASCII 栅格，精准定位行列号"""
        proj_x, proj_y = self.get_proj_xy(latitude, longitude)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            target_asc = Path(tmpdir) / file_path.stem
            with gzip.open(file_path, 'rb') as f_in:
                with open(target_asc, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    
            with rasterio.open(target_asc) as src:
                map_data = src.read(1)
                file_transform = src.transform
                row, col = rasterio.transform.rowcol(file_transform, proj_x, proj_y)
                
                if 0 <= row < src.height and 0 <= col < src.width:
                    val = map_data[row, col]
                    return float(val) if val > -9.0 else np.nan
                return np.nan

    def extract_time_series(self, latitude: float, longitude: float, start_date: str, end_date: str, variable: str = "ETo") -> pd.DataFrame:
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        results = []

        for date in date_range:
            file_path = self.data_root / date.strftime('%Y') / date.strftime('%m') / date.strftime('%d') / f"{variable}.asc.gz"
            val = np.nan
            if file_path.exists():
                try:
                    val = self.extract_point_value(file_path, latitude, longitude)
                except Exception:
                    val = np.nan
            results.append({"Date": date, variable: val})
            
        df = pd.DataFrame(results)
        if not df.empty:
            df.set_index("Date", inplace=True)
        return df

    def extract_from_nc_dataset(self, nc_path: Path, latitude: float, longitude: float, start_date: str, end_date: str, var_name: str = "eto") -> pd.DataFrame:
        """
        🎯 针对 30m 经纬度 WGS84 格式 NetCDF 优化的点提取函数
        """
        nc_path = Path(nc_path)
        if not nc_path.exists():
            raise FileNotFoundError(f"❌ 找不到您的 30m nc 文件: {nc_path}")
            
        with xr.open_dataset(nc_path) as ds:
            # 1. 自动识别维度
            x_dim = 'x' if 'x' in ds.dims else 'lon'
            y_dim = 'y' if 'y' in ds.dims else 'lat'
            time_dim = 'time' if 'time' in ds.dims else 'date'
            
            # 2. 核心修正：因为你的 30m NC 本身就是经纬度坐标，
            # 提取时【绝对不需要】转换成投影米，直接用原始的 longitude 和 latitude 丢进去！
            try:
                # 3. 剥离多余的 band 维度，直接锁定第一层
                if 'band' in ds.dims:
                    matrix_zone = ds[var_name].isel(band=0)
                else:
                    matrix_zone = ds[var_name]

                # 4. 空间最近邻切片 + 时间段截取
                slice_ds = matrix_zone.sel({x_dim: longitude, y_dim: latitude}, method="nearest")
                slice_time = slice_ds.sel({time_dim: slice(start_date, end_date)})
                
                # 5. 转换为 DataFrame 
                df_nc = slice_time.to_dataframe().reset_index()
                df_nc.rename(columns={time_dim: 'Date', var_name: 'ETo_30m'}, inplace=True)
                df_nc.set_index('Date', inplace=True)
                
                print(f"📍 30-m NC 空间对齐成功！正在使用原始经纬度 ({longitude}, {latitude}) 进行像素穿透。")
                return df_nc[['ETo_30m']]
                
            except Exception as e:
                raise RuntimeError(f"提取 30m NC 数据失败，错误详情: {e}")