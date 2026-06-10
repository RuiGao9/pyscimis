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
    """ETo comparison engine:
    Two datasets are:
    1. Spatial CIMIS dataset is downloaded and stored locally in a structured directory
    2. 30-m ETo NetCDF files are also stored locally, organized by month. For more details, please:
        wait for Rui's new released publications
        or directly contact Rui via email: Rui.Ray.Gao@Gmail.com or RuiGao@UCMerced.edu
    """

    def __init__(self, data_root_dir: str):
        self.data_root = Path(data_root_dir)
        # Coordinate systems for transformation
        self.wgs84 = Proj(init='epsg:4326')
        self.cal_albers = Proj(init='epsg:3310')

    def get_proj_xy(self, latitude: float, longitude: float):
        """Accurately and safely transform WGS84 lat/lon to California Albers projected coordinates (X, Y) in meters"""
        proj_x, proj_y = transform(self.wgs84, self.cal_albers, longitude, latitude)
        return proj_x, proj_y

    def load_corrected_raster(self, file_path: Path):
        """Correctly handle gzipped CIMIS ASCII raster files, ensuring the integrity of the data during decompression and loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_asc = Path(tmpdir) / file_path.stem
            with gzip.open(file_path, 'rb') as f_in:
                with open(target_asc, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            with rasterio.open(target_asc) as src:
                map_data = src.read(1)
                # Obtaining dynamic bounds from rasterio
                bounds = src.bounds
                extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
                return map_data, extent, src

    def extract_point_value(self, file_path: Path, latitude: float, longitude: float) -> float:
        """Dynamically parse official ASCII rasters and accurately locate row and column indices 
        for the given latitude and longitude, 
        ensuring robust handling of edge cases and out-of-bounds scenarios."""
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

    def extract_from_nc_dataset(self, nc_dir_path: str, latitude: float, longitude: float, start_date: str, end_date: str, var_name: str = "eto") -> pd.DataFrame:
        """
        A function to extract daily ETo values from a directory of 30-m NetCDF files
        """
        nc_dir = Path(nc_dir_path)
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        # Temporary list to store daily extraction results
        daily_results = []
        # Ovoid repeatedly opening and closing the same NetCDF files by caching opened datasets in memory
        opened_datasets = {}
        
        for date in date_range:
            # This part should be adjusted if users' situations is different compared with mine
            # My 20-m ETo NetCDF files are organized by month, and the name is like: CA_ETo_2021_05.nc
            # For example, 2021-05-01 (or 2021-05-31) corresponds to CA_ETo_2021_05.nc
            nc_filename = f"CA_ETo_{date.strftime('%Y_%m')}.nc"
            nc_file_path = nc_dir / nc_filename
            val = np.nan
            
            if nc_file_path.exists():
                try:
                    # Read this month's NetCDF file into memory if it hasn't been opened yet, otherwise reuse the cached dataset
                    if nc_filename not in opened_datasets:
                        opened_datasets[nc_filename] = xr.open_dataset(nc_file_path)
                    ds = opened_datasets[nc_filename]
                    
                    # Obtaining the dimensions for the spatial coordinates
                    x_dim = 'x' if 'x' in ds.dims else 'lon'
                    y_dim = 'y' if 'y' in ds.dims else 'lat'
                    time_dim = 'time' if 'time' in ds.dims else 'date'
                    
                    # Ignore the extra band dimension
                    matrix_zone = ds[var_name].isel(band=0) if 'band' in ds.dims else ds[var_name]
                    
                    # Spatial nearest-neighbor slicing, simultaneously pinpointing to this day
                    # Using np.datetime64 to ensure perfect matching with xarray's time axis type
                    target_time = np.datetime64(date.strftime('%Y-%m-%d'))
                    slice_val = matrix_zone.sel({x_dim: longitude, y_dim: latitude, time_dim: target_time}, method="nearest")
                    val = float(slice_val.values)
                    
                except Exception as e:
                    # If the extraction fails for a particular day, allow it to return NaN to ensure the long time series is not interrupted
                    pass
            else:
                # If a file for a particular month is missing, print a warning
                print(f"Warning: Missing 30m NC file: {nc_filename}")
            daily_results.append({"Date": date, "ETo_30m": val})
            
        # Close all cached file handles to release system memory
        for ds_obj in opened_datasets.values():
            ds_obj.close()
            
        # Assemble into the final long-term DataFrame
        df_nc = pd.DataFrame(daily_results)
        if not df_nc.empty:
            df_nc.set_index('Date', inplace=True)
            
        return df_nc
    
    def save_results(self, df: pd.DataFrame, output_path: str = None, save_output: bool = True) -> bool:
        """
        Save the dataframe to a CSV file with robust error handling and user-friendly feedback.
        
        Args:
            df (pd.DataFrame): Merged time-series DataFrame.
            output_path (str): User-specified complete save path (e.g., D:/.../ETo.csv).
            save_output (bool): Whether to execute the save operation. Default is True.
            
        Returns:
            bool: Returns True if saving is successful, False if not saved or failed.
        """
        # 1. Check if the user wants to save and if a path is provided
        if not save_output:
            print("Data preservation skipped (save_output is set to False).")
            return False
        if not output_path:
            print("Warning: save_output is True, but no output_path was provided. Skipped.")
            return False

        # 2. Safety save logic
        try:
            out_file = Path(output_path)
            # Automatically create all non-existent parent directories
            out_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Export as a research-standard CSV with date index
            df.to_csv(out_file, index=True)
            print(f"Success! Final comparison dataset safely saved to:\n   {out_file}")
            return True
            
        except Exception as e:
            # Even if the disk is full or the file is locked by Excel, it can gracefully intercept and prevent the entire Notebook from crashing
            print(f"Warning: Failed to save the dataset. Error details: {e}")
            return False