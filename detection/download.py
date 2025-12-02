from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import ee
from .gee_utils import initialize_gee

@csrf_exempt
def get_download_urls(request):
    """Generate GeoTIFF download URL at 10m resolution with all analysis layers"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            roi = data.get('roi')
            analysis_type = data.get('analysis_type', 'water')
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            
            if not roi or not start_date or not end_date:
                return JsonResponse({
                    'success': False, 
                    'error': 'Missing required parameters'
                })
            
            if not initialize_gee():
                return JsonResponse({
                    'success': False, 
                    'error': 'Google Earth Engine initialization failed'
                })
            
            # Handle both Feature and direct geometry
            if 'geometry' in roi:
                geometry = ee.Geometry(roi['geometry'])
            else:
                geometry = ee.Geometry(roi)
            
            # Get Sentinel-2 collection
            collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                         .filterBounds(geometry)
                         .filterDate(start_date, end_date)
                         .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
                         .median())
            
            # Resample to 10m resolution for all analysis types
            collection_resampled = collection.resample('bilinear').reproject(
                crs='EPSG:4326',
                scale=10
            )
            
            # Calculate all indices
            ndvi = collection_resampled.normalizedDifference(['B8', 'B4']).rename('NDVI')
            evi = collection_resampled.expression(
                '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                {'NIR': collection_resampled.select('B8'), 'RED': collection_resampled.select('B4'), 'BLUE': collection_resampled.select('B2')}
            ).rename('EVI')
            mndwi = collection_resampled.normalizedDifference(['B3', 'B11']).rename('MNDWI')
            ndwi = collection_resampled.normalizedDifference(['B3', 'B8']).rename('NDWI')
            ndmi = collection_resampled.normalizedDifference(['B8', 'B11']).rename('NDMI')
            
            # Create analysis-specific layers
            if analysis_type == 'water':
                # Water analysis layers with water mask
                water_mask = ndwi.gt(0.3).Or(mndwi.gt(0.3)).rename('Water_Mask')
                permanent_water = water_mask.rename('Permanent_Water')
                turbidity = collection_resampled.select('B4').divide(collection_resampled.select('B3')).updateMask(water_mask).rename('Turbidity')
                chlorophyll = collection_resampled.select('B8').divide(collection_resampled.select('B4')).updateMask(water_mask).rename('Chlorophyll')
                
                export_image = collection_resampled.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11']).addBands([
                    ndvi, evi, mndwi, ndwi, ndmi, water_mask, permanent_water, turbidity, chlorophyll
                ])
                scale = 10
                
            elif analysis_type == 'farm':
                # Farm analysis layers
                healthy_crops = ndvi.gt(0.5).rename('Healthy_Crops')
                stressed_crops = ndvi.gt(0.2).And(ndvi.lte(0.5)).rename('Stressed_Crops')
                bare_soil = ndvi.lte(0.2).rename('Bare_Soil')
                vci = ndvi.multiply(100).rename('VCI')
                
                export_image = collection_resampled.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11']).addBands([
                    ndvi, evi, mndwi, ndwi, ndmi, vci, healthy_crops, stressed_crops, bare_soil
                ])
                scale = 10
                
            else:
                # Default - all indices
                export_image = collection_resampled.select(['B2', 'B3', 'B4', 'B5', 'B8', 'B11']).addBands([
                    ndvi, evi, mndwi, ndwi, ndmi
                ])
            
            scale = 10
            
            # Calculate ROI area to determine export strategy
            roi_area = geometry.area().getInfo()  # in square meters
            roi_area_km2 = roi_area / 1e6
            
            # Adjust scale based on area size
            if roi_area_km2 > 10:
                scale = 30
            elif roi_area_km2 > 50:
                scale = 50
            else:
                scale = 10
            
            # Create a simple RGB visualization that's immediately visible
            # Scale RGB values to 0-255 range for proper display
            rgb = collection_resampled.select(['B4', 'B3', 'B2']).divide(10000).multiply(255).clamp(0, 255).uint8()
            
            # Create visualization based on analysis type
            if analysis_type == 'water':
                # Water in blue, land in RGB
                water_viz = water_mask.multiply(255).uint8()
                export_image = rgb.addBands(water_viz.rename('Water'))
            elif analysis_type == 'farm':
                # NDVI visualization (0-1 scaled to 0-255)
                ndvi_viz = ndvi.multiply(255).clamp(0, 255).uint8().rename('NDVI')
                export_image = rgb.addBands(ndvi_viz)
            else:
                # Just RGB
                export_image = rgb
            
            # Clip to ROI
            export_image = export_image.clip(geometry)
            
            # Get the bounding box for export
            bounds = geometry.bounds().getInfo()['coordinates']
            
            # Generate download URL
            try:
                tiff_url = export_image.getDownloadURL({
                    'name': f'{analysis_type}_analysis_{scale}m',
                    'region': bounds,
                    'scale': scale,
                    'crs': 'EPSG:4326',
                    'fileFormat': 'GeoTIFF'
                })
            except Exception as download_error:
                # If still too large, use lower resolution
                scale = 100
                export_image = rgb.clip(geometry)
                
                tiff_url = export_image.getDownloadURL({
                    'name': f'{analysis_type}_analysis_{scale}m',
                    'region': bounds,
                    'scale': scale,
                    'crs': 'EPSG:4326',
                    'fileFormat': 'GeoTIFF'
                })
            
            return JsonResponse({
                'success': True,
                'tiff_url': tiff_url,
                'resolution': f'{scale}m',
                'bands': export_image.bandNames().getInfo()
            })
            
        except Exception as e:
            import traceback
            return JsonResponse({
                'success': False, 
                'error': str(e),
                'details': traceback.format_exc()
            })
    
    return JsonResponse({'success': False, 'error': 'Only POST method allowed'})