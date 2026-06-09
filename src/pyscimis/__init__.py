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

    # def extract_from_nc_dataset(self, nc_path: Path, latitude: float, longitude: float, start_date: str, end_date: str, var_name: str = "eto") -> pd.DataFrame:
    #     """
    #     🎯 针对 30m 经纬度 WGS84 格式 NetCDF 优化的点提取函数
    #     """
    #     nc_path = Path(nc_path)
    #     if not nc_path.exists():
    #         raise FileNotFoundError(f"❌ 找不到您的 30m nc 文件: {nc_path}")
            
    #     with xr.open_dataset(nc_path) as ds:
    #         # 1. 自动识别维度
    #         x_dim = 'x' if 'x' in ds.dims else 'lon'
    #         y_dim = 'y' if 'y' in ds.dims else 'lat'
    #         time_dim = 'time' if 'time' in ds.dims else 'date'
            
    #         # 2. 核心修正：因为你的 30m NC 本身就是经纬度坐标，
    #         # 提取时【绝对不需要】转换成投影米，直接用原始的 longitude 和 latitude 丢进去！
    #         try:
    #             # 3. 剥离多余的 band 维度，直接锁定第一层
    #             if 'band' in ds.dims:
    #                 matrix_zone = ds[var_name].isel(band=0)
    #             else:
    #                 matrix_zone = ds[var_name]

    #             # 4. 空间最近邻切片 + 时间段截取
    #             slice_ds = matrix_zone.sel({x_dim: longitude, y_dim: latitude}, method="nearest")
    #             slice_time = slice_ds.sel({time_dim: slice(start_date, end_date)})
                
    #             # 5. 转换为 DataFrame 
    #             df_nc = slice_time.to_dataframe().reset_index()
    #             df_nc.rename(columns={time_dim: 'Date', var_name: 'ETo_30m'}, inplace=True)
    #             df_nc.set_index('Date', inplace=True)
                
    #             print(f"📍 30-m NC 空间对齐成功！正在使用原始经纬度 ({longitude}, {latitude}) 进行像素穿透。")
    #             return df_nc[['ETo_30m']]
                
    #         except Exception as e:
    #             raise RuntimeError(f"提取 30m NC 数据失败，错误详情: {e}")

    def extract_from_nc_dataset(self, nc_dir_path: str, latitude: float, longitude: float, start_date: str, end_date: str, var_name: str = "eto") -> pd.DataFrame:
        """
        🎯 月度 NC 动态路由版：自动根据日期范围拆分月份，穿透对应的多个 CA_ETo_YYYY_MM.nc 文件
        """
        nc_dir = Path(nc_dir_path)
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # 用来临时存放每天提取到的结果
        daily_results = []
        
        # 建立一个文件句柄缓存，避免频繁打开/关闭同一个 NC 文件提高效率
        opened_datasets = {}
        
        print(f"🔄 正在分析时空立方体目录，自动穿透跨月数据...")
        
        for date in date_range:
            # 🎯 核心逻辑：动态生成这一天对应的文件名
            # 比如 2021-05-01 对应 CA_ETo_2021_05.nc
            nc_filename = f"CA_ETo_{date.strftime('%Y_%m')}.nc"
            nc_file_path = nc_dir / nc_filename
            
            val = np.nan
            
            if nc_file_path.exists():
                try:
                    # 如果这个文件还没打开过，读入内存缓存
                    if nc_filename not in opened_datasets:
                        opened_datasets[nc_filename] = xr.open_dataset(nc_file_path)
                    
                    ds = opened_datasets[nc_filename]
                    
                    # 自动识别坐标轴维度
                    x_dim = 'x' if 'x' in ds.dims else 'lon'
                    y_dim = 'y' if 'y' in ds.dims else 'lat'
                    time_dim = 'time' if 'time' in ds.dims else 'date'
                    
                    # 剥离多余的 band 维度
                    matrix_zone = ds[var_name].isel(band=0) if 'band' in ds.dims else ds[var_name]
                    
                    # 空间最近邻切片，同时精确定位到【这一天】
                    # 使用 np.datetime64 确保与 xarray 的时间轴类型完美匹配
                    target_time = np.datetime64(date.strftime('%Y-%m-%d'))
                    slice_val = matrix_zone.sel({x_dim: longitude, y_dim: latitude, time_dim: target_time}, method="nearest")
                    
                    val = float(slice_val.values)
                    
                except Exception as e:
                    # 某一天如果提取失败，允许它返回 NaN 确保长时序不中断
                    pass
            else:
                # 如果某个月的文件不存在，打印提示
                print(f"⚠️ 提示: 缺失 30m NC 文件: {nc_filename}")
                
            daily_results.append({"Date": date, "ETo_30m": val})
            
        # 彻底关闭所有缓存的文件句柄，释放系统内存
        for ds_obj in opened_datasets.values():
            ds_obj.close()
            
        # 组装成最终的长时序 DataFrame
        df_nc = pd.DataFrame(daily_results)
        if not df_nc.empty:
            df_nc.set_index('Date', inplace=True)
            
        return df_nc