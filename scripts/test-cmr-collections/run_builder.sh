!#/bin/bash

# datasets that work
# going through https://search.earthdata.nasa.gov/search?q=C2532426483-ORNL_CLOUD&ff=Available%20in%20Earthdata%20Cloud&fl=3%2B-%2BGridded%2BObservations!4%2B-%2BGridded%2BModel%2BOutput&gdf=NetCDF&lat=38.81570252135013&long=-281.8125&zoom=0

# micasa dataset
python titiler_cmr_params_builder.py --collection-id C3273639213-GES_DISC

# gpm dataset
python titiler_cmr_params_builder.py --collection-id C2723754864-GES_DISC

# gldas dataset
python titiler_cmr_params_builder.py --collection-id C1933574500-GES_DISC

# what could work
- nested data, we could add group support but don't currently have it
  - C2930763263-LARC_CLOUD product data (TEMPO gridded NO2 tropospheric and stratospheric columns V03 (PROVISIONAL))
  - # TEMPO weights data may work but we don't currently have access to LARC cloud
  - GPM HDF5 datasets
- daymet - "IndexVariable objects must be 1-dimensional" - lat and lon are 2D

