from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import ee
import logging
from .gee_utils import initialize_gee, generate_time_series, get_weather_data, calculate_soil_moisture_index

logger = logging.getLogger(__name__)

def get_index_legend(index_type):
    """Get legend for different indices"""
    legends = {
        'ndvi': {
            'Low (0.0-0.2)': '#FF4500',
            'Moderate (0.2-0.4)': '#FFFF00',
            'Good (0.4-0.6)': '#32CD32',
            'Excellent (0.6-0.8)': '#006400'
        },
        'evi': {
            'Low (0.0-0.15)': '#FF4500',
            'Moderate (0.15-0.3)': '#FFFF00',
            'Good (0.3-0.45)': '#32CD32',
            'Excellent (0.45-0.6)': '#006400'
        },
        'ndmi': {
            'Dry (-0.5-0.0)': '#DAA520',
            'Moderate (0.0-0.2)': '#FFD700',
            'Moist (0.2-0.3)': '#87CEEB',
            'Very Moist (0.3-0.5)': '#191970'
        },
        'vci': {
            'Poor (0-25)': '#FF4500',
            'Fair (25-50)': '#FFFF00',
            'Good (50-75)': '#32CD32',
            'Excellent (75-100)': '#006400'
        }
    }
    return legends.get(index_type, legends['ndvi'])

@csrf_exempt
def analyze_farm_roi(request):
    """Basic farm analysis for vegetation indices"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            roi = data.get('roi')
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            compare_start = data.get('compareStartDate')
            compare_end = data.get('compareEndDate')
            index_type = data.get('indexType', 'ndvi')
            
            # Store original dates for time series
            original_start = data.get('originalStartDate', start_date)
            original_end = data.get('originalEndDate', end_date)
            
            if not initialize_gee():
                return JsonResponse({'success': False, 'error': 'GEE initialization failed'})
            
            geometry = ee.Geometry(roi['geometry'])
            
            # Get Sentinel-2 collections with fallback
            def get_collection(start, end):
                coll = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                    .filterBounds(geometry) \
                    .filterDate(start, end) \
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                if coll.size().getInfo() == 0:
                    coll = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                        .filterBounds(geometry) \
                        .filterDate(start, end)
                    if coll.size().getInfo() == 0:
                        coll = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
                            .filterBounds(geometry) \
                            .filterDate(start, end)
                return coll.median()
            
            collection1 = get_collection(start_date, end_date)
            collection2 = get_collection(compare_start, compare_end)
            
            # Calculate vegetation indices
            if index_type == 'ndvi':
                index1 = collection1.normalizedDifference(['B8', 'B4'])
                index2 = collection2.normalizedDifference(['B8', 'B4'])
                vis_params = {'min': 0, 'max': 1, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            elif index_type == 'evi':
                index1 = collection1.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                    {'NIR': collection1.select('B8'), 'RED': collection1.select('B4'), 'BLUE': collection1.select('B2')})
                index2 = collection2.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                    {'NIR': collection2.select('B8'), 'RED': collection2.select('B4'), 'BLUE': collection2.select('B2')})
                vis_params = {'min': 0, 'max': 0.6, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            elif index_type == 'ndmi':
                index1 = collection1.normalizedDifference(['B8', 'B11'])
                index2 = collection2.normalizedDifference(['B8', 'B11'])
                vis_params = {'min': -0.5, 'max': 0.5, 'palette': ['DAA520', 'FFD700', '87CEEB', '191970']}
            else:  # vci
                ndvi1 = collection1.normalizedDifference(['B8', 'B4'])
                ndvi2 = collection2.normalizedDifference(['B8', 'B4'])
                index1 = ndvi1.multiply(100)
                index2 = ndvi2.multiply(100)
                vis_params = {'min': 0, 'max': 100, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            
            # Calculate mean values
            mean1 = index1.reduceRegion(reducer=ee.Reducer.mean(), geometry=geometry, scale=30, maxPixels=1e13, bestEffort=True).getInfo()
            mean2 = index2.reduceRegion(reducer=ee.Reducer.mean(), geometry=geometry, scale=30, maxPixels=1e13, bestEffort=True).getInfo()
            
            area1 = float(list(mean1.values())[0] if mean1.values() else 0)
            area2 = float(list(mean2.values())[0] if mean2.values() else 0)
            change = float(area2 - area1)
            percentage = float((change / area1) * 100) if area1 > 0 else 0.0
            
            # Calculate actual vegetation areas based on index values
            total_area = float(ee.Geometry(roi['geometry']).area().getInfo() / 4047)  # Convert to acres
            
            # Calculate healthy vs stressed vegetation based on index values
            if index_type == 'ndvi':
                healthy_mask = index1.gt(0.4)  # Good + Excellent categories
                stressed_mask = index1.gt(0.0).And(index1.lte(0.4))  # Low + Moderate categories
            elif index_type == 'evi':
                healthy_mask = index1.gt(0.3)  # Good + Excellent categories  
                stressed_mask = index1.gt(0.0).And(index1.lte(0.3))  # Low + Moderate categories
            elif index_type == 'ndmi':
                healthy_mask = index1.gt(0.2)  # Moist + Very Moist categories
                stressed_mask = index1.gt(-0.5).And(index1.lte(0.2))  # Dry + Moderate categories
            else:  # vci
                healthy_mask = index1.gt(50)  # Good + Excellent categories
                stressed_mask = index1.gt(0).And(index1.lte(50))  # Poor + Fair categories
            
            # Calculate areas in acres
            healthy_area_m2 = healthy_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geometry, scale=30, maxPixels=1e13, bestEffort=True).getInfo()
            stressed_area_m2 = stressed_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geometry, scale=30, maxPixels=1e13, bestEffort=True).getInfo()
            
            healthy_area = float((list(healthy_area_m2.values())[0] if healthy_area_m2.values() else 0) / 4047)
            stressed_area = float((list(stressed_area_m2.values())[0] if stressed_area_m2.values() else 0) / 4047)
            health_score = float((healthy_area / (healthy_area + stressed_area) * 100) if (healthy_area + stressed_area) > 0 else 0)
            
            # Generate visualization with proper masking
            vegetation_mask = index1.gt(-1)  # Basic vegetation mask
            index1_vis = index1.updateMask(vegetation_mask).visualize(**vis_params).clip(geometry)
            index1_url = index1_vis.getMapId()['tile_fetcher'].url_format
            
            # Create individual layers for each vegetation health category
            individual_layers = {}
            legend = get_index_legend(index_type)
            
            if index_type == 'ndvi':
                thresholds = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8)]
                colors = ['FF4500', 'FFFF00', '32CD32', '006400']
            elif index_type == 'evi':
                thresholds = [(0.0, 0.15), (0.15, 0.3), (0.3, 0.45), (0.45, 0.6)]
                colors = ['FF4500', 'FFFF00', '32CD32', '006400']
            elif index_type == 'ndmi':
                thresholds = [(-0.5, 0.0), (0.0, 0.2), (0.2, 0.3), (0.3, 0.5)]
                colors = ['DAA520', 'FFD700', '87CEEB', '191970']
            else:  # vci
                thresholds = [(0, 25), (25, 50), (50, 75), (75, 100)]
                colors = ['FF4500', 'FFFF00', '32CD32', '006400']
            
            for i, (category_name, color) in enumerate(legend.items()):
                min_val, max_val = thresholds[i]
                if i == len(thresholds) - 1:  # Last category - use gte for upper bound
                    category_mask = index1.gte(min_val)
                else:
                    category_mask = index1.gte(min_val).And(index1.lt(max_val))
                
                # Mask the index values and visualize with solid color
                masked_index = index1.updateMask(category_mask)
                category_layer = masked_index.visualize(
                    min=min_val, max=max_val, palette=[colors[i], colors[i]]
                ).clip(geometry)
                layer_url = category_layer.getMapId()['tile_fetcher'].url_format
                individual_layers[category_name] = layer_url
                print(f"Created layer for {category_name}: {layer_url[:50]}...")
            
            print(f"Final individual_layers: {list(individual_layers.keys())}")
            
            # Get weather data
            weather_data = get_weather_data(geometry, start_date, end_date)
            
            # Get soil moisture index
            soil_moisture = calculate_soil_moisture_index(collection1, geometry)
            
            return JsonResponse({
                'success': True,
                'data': {
                    'area1': area1,
                    'area2': area2,
                    'change': change,
                    'percentage': percentage,
                    'breakdown': {
                        'healthy_veg': healthy_area,
                        'stressed_veg': stressed_area
                    },
                    'total_crop_area': total_area,
                    'health_score': health_score,
                    'layers': {
                        'main_index': index1_url,
                        'individual_categories': individual_layers
                    },
                    'legend': legend,
                    'time_series': generate_time_series(geometry, original_start, original_end, index_type.upper()),
                    'preloaded_time_series': True,
                    'weather': weather_data,
                    'soil_moisture': soil_moisture
                }
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@csrf_exempt
def preview_index(request):
    """Preview vegetation index visualization"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            roi = data.get('roi')
            index_type = data.get('indexType', 'ndvi')
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            
            if not initialize_gee():
                return JsonResponse({'success': False, 'error': 'GEE initialization failed'})
            
            geometry = ee.Geometry(roi['geometry'])
            
            collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                         .filterBounds(geometry)
                         .filterDate(start_date, end_date)
                         .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                         .median())
            
            if index_type == 'ndvi':
                index = collection.normalizedDifference(['B8', 'B4'])
                vis_params = {'min': 0, 'max': 1, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            elif index_type == 'evi':
                index = collection.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                    {'NIR': collection.select('B8'), 'RED': collection.select('B4'), 'BLUE': collection.select('B2')})
                vis_params = {'min': 0, 'max': 0.6, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            elif index_type == 'ndmi':
                index = collection.normalizedDifference(['B8', 'B11'])
                vis_params = {'min': -0.5, 'max': 0.5, 'palette': ['DAA520', 'FFD700', '87CEEB', '191970']}
            else:  # vci
                ndvi = collection.normalizedDifference(['B8', 'B4'])
                index = ndvi.multiply(100)
                vis_params = {'min': 0, 'max': 100, 'palette': ['FF4500', 'FFFF00', '32CD32', '006400']}
            
            map_id = index.visualize(**vis_params).getMapId()
            preview_url = map_id['tile_fetcher'].url_format
            
            return JsonResponse({
                'success': True,
                'data': {
                    'preview_layer': preview_url,
                    'legend': get_index_legend(index_type)
                }
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

