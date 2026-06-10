# How do I get ETo from the spatial CIMIS and one 30-m ETo dataset?
>_Once you open the CIMIS website (new version), you can quickly check data from the nearest station. If you want to know the ETo at a specific location for a specific time period, you may want to check this repository based on the **spatial CIMIS** dataset.<br> Because we are working on high-resolution ETo, we also provide the corresponding ETo as a reference._

## Requirements
1. A location within California state.
2. Raw spatial CIMIS data should be downloaded locally.
3. The 30-m ETo products should also downloaded locally.
   
## Features
After running this program, you are suppose to get:
1. The ETo extracted from the 2-km pixel resolution spatial CIMIS ETo maps at the location you defined.
2. The corresponding ETo extracted from another resources, 30-m pixel resolution spatial ETo maps, at the location you defined.
3. A time-series ETo comparison figure.
4. A _*.CSV_ format document containing the ETo values and the corresponding time stamp.

## Installation
```bash
pip install "git+https://github.com/RuiGao9/pyscimis.git"
```

## How to Use This Repository for Data Downloading
The second section of `RunThis.ipynb` should be editted based on your questions. Like below:

```python
# Do you want to save the output to a CSV file? If yes:
save_output = True  # If no, change to False
# Fold location to save the final dataframe
output_path = r"C:\GitHub\pyscimis\output\ETo_Comparison.csv"

# Define the folder where the CIMIS data is stored
CIMIS_DATA_DIR = r"D:\1_Postdoc\0_Data\4_CIMIS_Spatial\Download"
# Define the folder where your 30-m ETo data is stored
# Detailed inforamtion about this dataset can ask Rui for more details
# Rui's Emails: Rui.Ray.Gao@Gmail.com or RuiGao@UCMerced.edu
MY_NC_DATA_DIR = r"E:\6_ETo_30m"
# Define the start and end dates
start_date = "2021-01-01"
end_date = "2021-12-31"
# Define the latitude and longitude for the point of interest
[latitude, longitude] = [37.354999, -120.414366]
```
## Reference
Gao, R., Safeeq, M., & Viers, J. H. (2026). California 30-m daily reference evapotranspiration dataset (2020): Version 1.0. Zenodo. https://doi.org/10.5281/zenodo.20388023<br>
_Note: The 30-m ETo dataset is currently available for 2018–2025. At this time, only the 2020 data have been released online. To request data for other years, please contact Rui using one of the email addresses listed at the end of this document._

## Citation
Gao, R., Safeeq, M., Viers, J.H. (2026). pyscimis: Automated time-series data extraction tool for spatial CIMIS dataset (Version Initial). Zenodo. https://doi.org/10.5281/zenodo.20603074

## Repository update information
- Creation date: 2026-06-08
- Last update: 2026-06-10

## Contact inforamtion if issues were found
Rui Gao: Rui.Ray.Gao@gmail.com or RuiGao@UCMerced.edu
