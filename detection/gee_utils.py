import ee
from datetime import datetime, timedelta
import calendar

def initialize_gee():
    """Initialize Google Earth Engine with user authentication"""
    try:
        # Check if already initialized
        try:
            ee.Number(1).getInfo()
            return True
        except:
            pass
        
        # Initialize with default credentials
        ee.Initialize()
        
        # Test if initialization worked
        ee.Number(1).getInfo()
        print("GEE initialized successfully")
        return True
        
    except Exception as e:
        print(f"GEE initialization error: {e}")
        print("Please run: earthengine authenticate")
        return False

def generate_time_series(geometry, start_date, end_date, analysis_type='WATER'):
    """Generate monthly time series data"""
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        months = []
        areas = []
        
        current = start.replace(day=1)
        while current <= end:
            # Get last day of current month
            last_day = calendar.monthrange(current.year, current.month)[1]
            month_end = current.replace(day=last_day)
            
            # Don't go beyond end date
            if month_end > end:
                month_end = end
            
            try:
                # Use Sentinel-2 for water detection
                collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                            .filterBounds(geometry)
                            .filterDate(current.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d'))
                            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
                            .limit(5))  # Limit collection size
                
                if collection.size().getInfo() > 0:
                    image = collection.median()
                    
                    if analysis_type == 'WATER':
                        # MNDWI for Sentinel-2
                        mndwi = image.normalizedDifference(['B3', 'B11'])
                        water = mndwi.gt(0.1)
                        area = water.multiply(ee.Image.pixelArea()).reduceRegion(
                            reducer=ee.Reducer.sum(), geometry=geometry, scale=100, maxPixels=1e7
                        ).getInfo()
                        value = float(next((v for v in area.values() if v), 0) / 1e6)
                    else:
                        # NDVI for vegetation
                        ndvi = image.normalizedDifference(['B8', 'B4'])
                        mean_value = ndvi.reduceRegion(
                            reducer=ee.Reducer.mean(), geometry=geometry, scale=100, maxPixels=1e7
                        ).getInfo()
                        value = float(next((v for v in mean_value.values() if v), 0))
                else:
                    value = 0
                    
            except Exception as e:
                print(f"Error processing month {current.strftime('%Y-%m')}: {e}")
                value = 0.0
            
            months.append(current.strftime('%Y-%m'))
            areas.append(value)
            
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        # Apply interpolation to fill gaps
        interpolated_areas = interpolate_missing_values(areas)
        
        return {
            'months': months,
            'areas': interpolated_areas,
            'index_type': analysis_type.upper() if analysis_type != 'WATER' else 'WATER'
        }
        
    except Exception as e:
        print(f"Time series generation failed: {e}")
        return {
            'months': [],
            'areas': [],
            'index_type': analysis_type.upper() if analysis_type != 'WATER' else 'WATER'
        }

def interpolate_missing_values(areas):
    """Interpolate missing (zero/None) values in time series data using linear interpolation"""
    if not areas or len(areas) <= 1:
        return areas
    
    interpolated = areas.copy()
    
    # Helper function to check if value is valid
    def is_valid(val):
        return val is not None and val != 0
    
    # Find first valid value
    first_valid = None
    for i, val in enumerate(areas):
        if is_valid(val):
            first_valid = i
            break
    
    if first_valid is None:
        # No valid values, return zeros
        return [0] * len(areas)
    
    # Fill values before first valid value
    for i in range(first_valid):
        interpolated[i] = areas[first_valid]
    
    # Interpolate between valid values
    for i in range(len(areas)):
        if not is_valid(areas[i]):
            # Find previous valid value
            prev_valid = None
            for k in range(i - 1, -1, -1):
                if is_valid(areas[k]):
                    prev_valid = k
                    break
            
            # Find next valid value
            next_valid = None
            for j in range(i + 1, len(areas)):
                if is_valid(areas[j]):
                    next_valid = j
                    break
            
            if prev_valid is not None and next_valid is not None:
                # Linear interpolation between two valid points
                steps = next_valid - prev_valid
                step_size = (areas[next_valid] - areas[prev_valid]) / steps
                interpolated[i] = round(areas[prev_valid] + step_size * (i - prev_valid), 3)
            elif prev_valid is not None:
                # No next valid value, use last known value
                interpolated[i] = areas[prev_valid]
            elif next_valid is not None:
                # No previous valid value, use next known value
                interpolated[i] = areas[next_valid]
            else:
                # No valid values found, set to 0
                interpolated[i] = 0
    
    return interpolated

def get_weather_data(geometry, start_date, end_date):
    """Get weather data (rainfall, temperature) from ERA5"""
    try:
        # ERA5 Daily Aggregates
        weather = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')\
            .filterBounds(geometry)\
            .filterDate(start_date, end_date)\
            .select(['temperature_2m', 'total_precipitation_sum'])
        
        # Calculate mean temperature (convert from Kelvin to Celsius)
        temp_image = weather.select('temperature_2m').mean().subtract(273.15)
        temp_stats = temp_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=1000,
            maxPixels=1e9
        ).getInfo()
        
        # Calculate total rainfall (convert from m to mm)
        rain_image = weather.select('total_precipitation_sum').sum().multiply(1000)
        rain_stats = rain_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=1000,
            maxPixels=1e9
        ).getInfo()
        
        avg_temp = float(temp_stats.get('temperature_2m', 0) or 0)
        total_rainfall = float(rain_stats.get('total_precipitation_sum', 0) or 0)
        
        # Determine stress factors
        stress_factors = []
        if avg_temp > 35:
            stress_factors.append('Heat Stress')
        elif avg_temp < 10:
            stress_factors.append('Cold Stress')
        
        if total_rainfall < 50:
            stress_factors.append('Drought')
        elif total_rainfall > 500:
            stress_factors.append('Excess Rainfall')
        
        return {
            'avg_temperature': round(avg_temp, 1),
            'total_rainfall': round(total_rainfall, 1),
            'stress_factors': stress_factors if stress_factors else ['Normal Conditions'],
            'temperature_status': 'Optimal' if 15 <= avg_temp <= 30 else 'Stressful',
            'rainfall_status': 'Adequate' if 100 <= total_rainfall <= 400 else 'Inadequate' if total_rainfall < 100 else 'Excessive'
        }
        
    except Exception as e:
        print(f"Weather data error: {e}")
        return {
            'avg_temperature': 0,
            'total_rainfall': 0,
            'stress_factors': ['Data Unavailable'],
            'temperature_status': 'Unknown',
            'rainfall_status': 'Unknown'
        }

def calculate_soil_moisture_index(image, geometry):
    """Calculate Soil Moisture Index using NDMI"""
    try:
        # NDMI (Normalized Difference Moisture Index)
        ndmi = image.normalizedDifference(['B8', 'B11']).rename('NDMI')
        
        # Calculate mean NDMI
        ndmi_stats = ndmi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=30,
            maxPixels=1e9
        ).getInfo()
        
        ndmi_value = float(ndmi_stats.get('NDMI', 0) or 0)
        
        # Classify moisture levels
        if ndmi_value > 0.3:
            moisture_level = 'Very Moist'
            moisture_status = 'Excellent'
            water_stress = 'None'
        elif ndmi_value > 0.2:
            moisture_level = 'Moist'
            moisture_status = 'Good'
            water_stress = 'Low'
        elif ndmi_value > 0.0:
            moisture_level = 'Moderate'
            moisture_status = 'Fair'
            water_stress = 'Moderate'
        elif ndmi_value > -0.2:
            moisture_level = 'Dry'
            moisture_status = 'Poor'
            water_stress = 'High'
        else:
            moisture_level = 'Very Dry'
            moisture_status = 'Critical'
            water_stress = 'Severe'
        
        # Calculate moisture areas
        very_moist = ndmi.gt(0.3)
        moist = ndmi.gt(0.2).And(ndmi.lte(0.3))
        moderate = ndmi.gt(0.0).And(ndmi.lte(0.2))
        dry = ndmi.gt(-0.2).And(ndmi.lte(0.0))
        very_dry = ndmi.lte(-0.2)
        
        def get_area(mask):
            area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=geometry,
                scale=30,
                maxPixels=1e9
            ).getInfo()
            return float((area.get('NDMI', 0) or 0) / 4047)  # Convert to acres
        
        return {
            'ndmi_value': round(ndmi_value, 3),
            'moisture_level': moisture_level,
            'moisture_status': moisture_status,
            'water_stress': water_stress,
            'areas': {
                'very_moist': round(get_area(very_moist), 2),
                'moist': round(get_area(moist), 2),
                'moderate': round(get_area(moderate), 2),
                'dry': round(get_area(dry), 2),
                'very_dry': round(get_area(very_dry), 2)
            },
            'irrigation_needed': water_stress in ['High', 'Severe']
        }
        
    except Exception as e:
        print(f"Soil moisture calculation error: {e}")
        return {
            'ndmi_value': 0,
            'moisture_level': 'Unknown',
            'moisture_status': 'Unknown',
            'water_stress': 'Unknown',
            'areas': {},
            'irrigation_needed': False
        }

def get_crop_specific_thresholds(crop_type):
    """Get crop-specific NDVI/EVI thresholds for accurate classification"""
    thresholds = {
        'rice': {
            'ndvi': {'low': 0.2, 'moderate': 0.4, 'good': 0.6, 'excellent': 0.75},
            'evi': {'low': 0.15, 'moderate': 0.3, 'good': 0.45, 'excellent': 0.6},
            'optimal_range': 'NDVI: 0.6-0.8, EVI: 0.45-0.65'
        },
        'wheat': {
            'ndvi': {'low': 0.15, 'moderate': 0.35, 'good': 0.55, 'excellent': 0.7},
            'evi': {'low': 0.1, 'moderate': 0.25, 'good': 0.4, 'excellent': 0.55},
            'optimal_range': 'NDVI: 0.55-0.75, EVI: 0.4-0.6'
        },
        'cotton': {
            'ndvi': {'low': 0.2, 'moderate': 0.4, 'good': 0.6, 'excellent': 0.75},
            'evi': {'low': 0.15, 'moderate': 0.3, 'good': 0.45, 'excellent': 0.6},
            'optimal_range': 'NDVI: 0.6-0.8, EVI: 0.45-0.65'
        },
        'maize': {
            'ndvi': {'low': 0.25, 'moderate': 0.45, 'good': 0.65, 'excellent': 0.8},
            'evi': {'low': 0.2, 'moderate': 0.35, 'good': 0.5, 'excellent': 0.65},
            'optimal_range': 'NDVI: 0.65-0.85, EVI: 0.5-0.7'
        },
        'sugarcane': {
            'ndvi': {'low': 0.3, 'moderate': 0.5, 'good': 0.7, 'excellent': 0.85},
            'evi': {'low': 0.25, 'moderate': 0.4, 'good': 0.55, 'excellent': 0.7},
            'optimal_range': 'NDVI: 0.7-0.9, EVI: 0.55-0.75'
        },
        'barley': {
            'ndvi': {'low': 0.15, 'moderate': 0.35, 'good': 0.55, 'excellent': 0.7},
            'evi': {'low': 0.1, 'moderate': 0.25, 'good': 0.4, 'excellent': 0.55},
            'optimal_range': 'NDVI: 0.55-0.75, EVI: 0.4-0.6'
        },
        'mustard': {
            'ndvi': {'low': 0.2, 'moderate': 0.4, 'good': 0.6, 'excellent': 0.75},
            'evi': {'low': 0.15, 'moderate': 0.3, 'good': 0.45, 'excellent': 0.6},
            'optimal_range': 'NDVI: 0.6-0.8, EVI: 0.45-0.65'
        },
        'default': {
            'ndvi': {'low': 0.2, 'moderate': 0.4, 'good': 0.6, 'excellent': 0.8},
            'evi': {'low': 0.15, 'moderate': 0.3, 'good': 0.45, 'excellent': 0.6},
            'optimal_range': 'NDVI: 0.6-0.8, EVI: 0.45-0.65'
        }
    }
    
    return thresholds.get(crop_type.lower(), thresholds['default'])
