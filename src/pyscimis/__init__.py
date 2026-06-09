import gzip
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
import xarray as xr

class LocalSpatialCimis:
    """完美融合 2km 官方 Spatial CIMIS 与 30m 个人高分 NetCDF 数据的科研级提取工具"""
    
    CIMIS_CRS = "EPSG:3310"  # California Albers
    WGS84_CRS = "EPSG:4326"  # 经纬度

    def __init__(self, data_root_dir: str):
        self.data_root = Path(data_root_dir)
        self.transformer = Transformer.from_crs(self.WGS84_CRS, self.CIMIS_CRS, always_xy=True)
        # 官方 2km ASCII 空间修正矩阵
        self.corrected_transform = from_origin(west=-374000, north=-166000, xsize=2000, ysize=2000)

    # =====================================================================
    # 官方 2km 空间数据提取逻辑
    # =====================================================================
    def load_corrected_raster(self, file_path: Path):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_asc = Path(tmpdir) / file_path.stem
            with gzip.open(file_path, 'rb') as f_in:
                with open(target_asc, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            with rasterio.open(target_asc) as src:
                map_data = src.read(1)
                xmin, ymin = -374000, -602000
                xmax = xmin + (src.width * 2000)
                ymax = ymin + (src.height * 2000)
                return map_data, [xmin, xmax, ymin, ymax], src

    def extract_point_value(self, file_path: Path, latitude: float, longitude: float) -> float:
        proj_x, proj_y = self.transformer.transform(longitude, latitude)
        with tempfile.TemporaryDirectory() as tmpdir:
            target_asc = Path(tmpdir) / file_path.stem
            with gzip.open(file_path, 'rb') as f_in:
                with open(target_asc, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            with rasterio.open(target_asc) as src:
                map_data = src.read(1)
                row, col = rasterio.transform.rowcol(self.corrected_transform, proj_x, proj_y)
                if 0 <= row < src.height and 0 <= col < src.width:
                    val = map_data[row, col]
                    return float(val) if val > -9.0 else np.nan
                return np.nan

    def extract_time_series(self, latitude: float, longitude: float, start_date: str, end_date: str, variable: str = "ETo") -> pd.DataFrame:
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        results = []
        for date in date_range:
            file_path = self.data_root / date.strftime('%Y') / date.strftime('%m') / date.strftime('%d') / f"{variable}.asc.gz"
            val = self.extract_point_value(file_path, latitude, longitude) if file_path.exists() else np.nan
            results.append({"Date": date, variable: val})
        df = pd.DataFrame(results)
        if not df.empty:
            df.set_index("Date", inplace=True)
        return df

    # =====================================================================
    # 🎯 你的 30m 高分辨率 NetCDF 提取核心逻辑
    # =====================================================================
    def extract_from_nc_dataset(self, nc_path: Path, latitude: float, longitude: float, start_date: str, end_date: str, var_name: str = "ETo") -> pd.DataFrame:
        """
        利用 Xarray 的近邻插值（Nearest Neighbor），直接穿透你的 30m NetCDF 时空立方体，一击必中提取时序。
        """
        nc_path = Path(nc_path)
        if not nc_path.exists():
            raise FileNotFoundError(f"❌ 找不到您的 30m nc 文件: {nc_path}")
            
        # 1. 转换坐标到 California Albers (EPSG:3310)
        proj_x, proj_y = self.transformer.transform(longitude, latitude)
        
        # 2. 用 xarray 打开时空立方体
        with xr.open_dataset(nc_path) as ds:
            # 自动识别维度名称（兼容大写或标准命名）
            x_dim = 'x' if 'x' in ds.dims else ('easting' if 'easting' in ds.dims else 'lon')
            y_dim = 'y' if 'y' in ds.dims else ('northing' if 'northing' in ds.dims else 'lat')
            time_dim = 'time' if 'time' in ds.dims else 'date'
            
            # 自动识别数据集里真正的变量名（防止你存的是小写 'eto' 或带有版本后缀）
            actual_var = var_name
            if var_name not in ds.variables:
                for v in ds.variables:
                    if var_name.lower() in v.lower():
                        actual_var = v
                        break

            # 3. 核心黑科技：利用 xarray.sel 进行空间最近邻切片，并截取时间段
            try:
                # 空间定位
                slice_ds = ds[actual_var].sel({x_dim: proj_x, y_dim: proj_y}, method="nearest")
                # 时间切片
                slice_time = slice_ds.sel({time_dim: slice(start_date, end_date)})
                
                # 4. 转化为标准的 Pandas DataFrame
                df_nc = slice_time.to_dataframe().reset_index()
                
                # 清洗列名，确保返回一致性
                df_nc.rename(columns={time_dim: 'Date', actual_var: 'ETo_30m'}, inplace=True)
                df_nc.set_index('Date', inplace=True)
                
                # 过滤无效值
                df_nc['ETo_30m'] = df_nc['ETo_30m'].where(df_nc['ETo_30m'] > -9000, np.nan)
                
                return df_nc[['ETo_30m']]
                
            except Exception as e:
                raise RuntimeError(f"提取 NC 数据时出错，请确认您的 NC 维度名称是否为 (time, y, x)。报错详情: {e}")

def convert_eto_to_metric(df: pd.DataFrame, column_name: str = "ETo") -> pd.DataFrame:
    df_metric = df.copy()
    if column_name in df_metric.columns:
        df_metric[f"{column_name}_mm"] = df_metric[column_name] * 25.4
    return df_metric