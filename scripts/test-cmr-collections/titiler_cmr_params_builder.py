from datetime import datetime
import numpy as np
import random
import requests
import tempfile
import xarray as xr
import cf_xarray
import morecantile
from urllib.parse import quote_plus
import argparse
import inquirer
import sys
from typing import Union

class TitilerCMRTileParamsBuilder:
    cmr_collection_search = f"https://cmr.earthdata.nasa.gov/search/collections.json"
    cmr_granules_search = f"https://cmr.earthdata.nasa.gov/search/granules.json"
    colormap_name = "gray"
    titiler_tile_url = "https://dev-titiler-cmr.delta-backend.com/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
    cog_suffixes = ['.tif', '.tiff']            
    # hdf_suffixes = ['.h5', '.hdf', '.hdf5']
    netcdf_suffixes = ['.nc', '.nc4']
    min_keys = ["valid_min", "actual_min", "minimum", "data_min", "vmin"]
    max_keys = ["valid_max", "actual_max", "maximum", "data_max", "vmax"]

    def __init__(self, collection_id: str, variable: str = None, protocol: str = "https"):
        # C1342986035-GES_DISC
        self.collection_id = collection_id
        self.collection = self.fetch_cmr_collection()
        self.protocol = protocol
        if self.protocol == "https":
            self.download_rel = "http://esipfed.org/ns/fedsearch/1.1/data#"
        elif self.protocol == "s3":
            self.download_rel = "http://esipfed.org/ns/fedsearch/1.1/s3#"
        self.variable = variable
        self.granule_id: str = None
        self.granule_url: str = None
        self.local_storage_path: str = None
        self.backend: Union["xarray", "rasterio"] = None

    def fetch_cmr_collection(self):
        # function which queries CMR for a collection
        # returns collection object
        params = {
            "cloud_hosted": True,
            "concept_id": self.collection_id
        }
        collection_response = requests.get(
            self.cmr_collection_search,
            params=params,
            headers={"Accept": "application/json"},
        )
        if collection_response.status_code != 200:
            raise ValueError("Error fetching collection from CMR")
        collection_json = collection_response.json()
        return collection_json["feed"]["entry"][0]        

    def select_random_date(self):
        # Get time_start and time_end from collection
        time_start = self.collection.get('time_start')
        time_end = self.collection.get('time_end', datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        
        # Convert to datetime objects
        start_dt = datetime.strptime(time_start, '%Y-%m-%dT%H:%M:%S.%fZ')
        end_dt = datetime.strptime(time_end, '%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Convert to timestamps for random selection
        start_ts = start_dt.timestamp()
        end_ts = end_dt.timestamp()
        
        # Generate random timestamp between start and end
        random_ts = random.uniform(start_ts, end_ts)
        
        # Convert back to datetime
        random_dt = datetime.fromtimestamp(random_ts)
        
        # Format as ISO string and store
        self.datetime = random_dt.strftime('%Y-%m-%dT00:00:00')
        return self.datetime

    def query_cmr_granule(self):
        """
        Query CMR for a granule using the collection_id and datetime
        Returns the first matching granule
        """
        if not hasattr(self, 'datetime') or not self.datetime:
            raise ValueError("No datetime set. Call select_random_date() first.")

        # Set up parameters for the granule search
        params = {
            "collection_concept_id": self.collection_id,
            "temporal[]": f"{self.datetime},", #{self.datetime}",  # Use the selected datetime
            "page_size": 1,  # We only need one granule
            "sort_key": "-start_date"  # Sort by start date descending
        }

        # Make the request to CMR
        response = requests.get(
            self.cmr_granules_search,
            params=params,
            headers={"Accept": "application/json"}
        )

        if response.status_code != 200:
            raise ValueError(f"Error fetching granules from CMR: {response.status_code}")

        granules_json = response.json()
        
        # Check if we got any granules
        if not granules_json.get("feed", {}).get("entry", []):
            raise ValueError(f"No granules found for collection {self.collection_id} at datetime {self.datetime}")

        # Get the first granule
        granule = granules_json["feed"]["entry"][0]
        
        # Store the granule ID
        self.granule_id = granule.get("id")
        
        # Look for the data download URL in the granule links
        if "links" in granule:
            for link in granule["links"]:
                if "href" in link and "rel" in link and link["rel"] == self.download_rel: 
                    href = link["href"]
                    # Check if the URL points to a supported file format
                    if any(href.lower().endswith(ext) for ext in self.cog_suffixes):
                        self.backend = "rasterio"
                    if any(href.lower().endswith(ext) for ext in self.netcdf_suffixes):
                        self.backend = "xarray"

                    if self.backend:
                        self.granule_url = href
                        break

        if self.backend is None:
            raise ValueError(f"No suitable backend found for granule {self.granule_id}")
        
        if not self.granule_url:
            raise ValueError(f"No suitable data URL found in granule {self.granule_id}")

        return granule
    
    def download_granule(self):
        # download granule
        # return path to granule
        if not self.granule_url:
            raise ValueError(f"No suitable data URL found in granule {self.granule_id}")
        response = requests.get(self.granule_url)
        if response.status_code != 200:
            raise ValueError(f"Error downloading granule: {response.status_code}")
        
        # Create a temporary file that will be automatically cleaned up
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(response.content)
            self.local_storage_path = temp_file.name
            
        return self.local_storage_path
    
    def calculate_tile_coordinates(self):
        """
        Calculate appropriate tile coordinates (x, y, z) for given bounds.
        Returns the zoom level where the dataset fits nicely into a viewport.
        
        Returns:
            tuple: (x, y, z) tile coordinates
        """
        # Use WebMercatorQuad tile matrix set (most common)
        tms = morecantile.tms.get("WebMercatorQuad")
        
        # Start with zoom level 0 and increase until we find a good fit
        zoom = 0
        while zoom < 22:  # Maximum zoom level in WebMercatorQuad
            # Get the tile matrix for this zoom level
            matrix = tms.matrix(zoom)
            
            # Calculate how many tiles would be needed at this zoom level
            tiles = list(tms.tiles(*self.bounds, zooms=[zoom]))
            
            # If we have more than 4 tiles, increase zoom
            if len(tiles) > 4:
                zoom += 1
            else:
                break
        
        # Get the first tile (most common case)
        tile = tiles[0]
        
        return tile.x, tile.y, tile.z

    def find_min_max_attrs(self, var: xr.Variable):
        min_val = next((var.attrs[key] for key in self.min_keys if key in var.attrs), None)
        max_val = next((var.attrs[key] for key in self.max_keys if key in var.attrs), None)
        if min_val is None or max_val is None:
            fill_value = var.attrs.get("_FillValue", None)
            data = var.values
            if fill_value is not None:
                non_null_values = data[data != fill_value] 
            else:
                non_null_values = data[~np.isnan(data)]
            if min_val is None:
                min_val = non_null_values.min()
            if max_val is None:
                max_val = non_null_values.max()
        return min_val, max_val

    # construct parameters
    def build_params(self):
        self.select_random_date()
        self.query_cmr_granule()
        self.download_granule()

        # for netcdf, determine variable and range
        if self.backend == "xarray":
            self.ds = xr.open_dataset(self.local_storage_path)
            if self.variable is None:
                # Get all variables that aren't coordinates
                available_vars = [var for var in self.ds.variables if var not in self.ds.coords]
                
                # If running as a script, use interactive selection
                if __name__ == "__main__":
                    questions = [
                        inquirer.List('variable',
                                    message="Select a variable to visualize",
                                    choices=available_vars,
                                    ),
                    ]
                    answers = inquirer.prompt(questions)
                    self.variable = answers['variable']
                else:
                    # If imported as a module, use the first non-coordinate variable
                    self.variable = available_vars[0]
            
            self.min, self.max = self.find_min_max_attrs(self.ds.variables[self.variable])
            
            # Get longitude and latitude variables using CF standard names
            try:
                # Get CF-compliant variables
                cf_vars = self.ds.cf.standard_names
                
                # Find longitude and latitude variables
                lon_var = cf_vars.get('longitude', ['lon'])[0]
                lat_var = cf_vars.get('latitude', ['lat'])[0]
                
                if lon_var is None or lat_var is None:
                    raise KeyError("Could not find longitude/latitude variables")
                
                # Calculate bounds from min/max of coordinates
                self.bounds = (
                    float(self.ds[lon_var].min()),
                    float(self.ds[lat_var].min()),
                    float(self.ds[lon_var].max()),
                    float(self.ds[lat_var].max())
                )
            except (KeyError, AttributeError) as e:
                raise ValueError(f"Could not determine bounds from dataset: {str(e)}")
        elif self.backend == "rasterio": # for geotiffs, determine band and range
            pass
 
        self.x, self.y, self.z = self.calculate_tile_coordinates()
        return self
    
    def gen_tile_url(self):
        base_url = self.titiler_tile_url.format(
            z=self.z,
            x=self.x,
            y=self.y
        )
        
        # Create query parameters dictionary
        params = {
            "concept_id": self.collection_id,
            "backend": self.backend,
            "datetime": self.datetime,
            "variable": self.variable,
            "colormap_name": self.colormap_name,
            "rescale": f"{self.min},{self.max}"
        }
        
        # URL encode each parameter and join them with &
        query_string = "&".join(
            f"{key}={str(value)}"
            for key, value in params.items()
            if value is not None
        )
        
        return f"{base_url}?{query_string}"

def main():
    parser = argparse.ArgumentParser(description='Generate tile parameters for titiler-cmr')
    parser.add_argument('--collection-id', required=True, help='CMR collection ID')
    parser.add_argument('--variable', help='Variable to visualize (optional)')
    parser.add_argument('--protocol', default='https', choices=['https', 's3'], help='Protocol to use for data access')
    
    args = parser.parse_args()
    
    builder = TitilerCMRTileParamsBuilder(
        collection_id=args.collection_id,
        variable=args.variable,
        protocol=args.protocol
    )
    
    builder.build_params()
    tile_url = builder.gen_tile_url()
    print(f"Generated tile URL: {tile_url}")

if __name__ == "__main__":
    main()
