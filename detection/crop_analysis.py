from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import ee
from .gee_utils import initialize_gee, generate_time_series, get_crop_specific_thresholds, get_weather_data

def determine_crop_season(start_date, end_date, season_type='auto'):
    """Determine Rabi/Kharif season and predict appropriate crops"""
    
    if season_type == 'kharif':
        season = 'Kharif'
        primary_crops = ['Rice', 'Sugarcane', 'Cotton', 'Maize']
        start_date = start_date.split('-')[0] + '-06-01'
        end_date = end_date.split('-')[0] + '-10-31'
    elif season_type == 'rabi':
        season = 'Rabi'
        primary_crops = ['Wheat', 'Barley', 'Mustard', 'Gram']
        year = int(start_date.split('-')[0])
        start_date = f"{year}-11-01"
        end_date = f"{year+1}-04-30"
    else:
        start_month = int(start_date.split('-')[1])
        
        if start_month >= 6 and start_month <= 10:
            season = 'Kharif'
            primary_crops = ['Rice', 'Sugarcane', 'Cotton', 'Maize']
        elif start_month >= 11 or start_month <= 4:
            season = 'Rabi'
            primary_crops = ['Wheat', 'Barley', 'Mustard', 'Gram']
        else:
            season = 'Transition'
            primary_crops = ['Mixed Crops']
    
    return season, primary_crops

def crop_type_identification(geometry, start_date, end_date, season_type='auto'):
    try:
        season, expected_crops = determine_crop_season(start_date, end_date, season_type)
        
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(geometry)
                     .filterDate(start_date, end_date)
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
                     .median())
        
        ndvi = collection.normalizedDifference(['B8', 'B4']).rename('NDVI')
        evi = collection.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': collection.select('B8'), 'RED': collection.select('B4'), 'BLUE': collection.select('B2')}).rename('EVI')
        mndwi = collection.normalizedDifference(['B3', 'B11']).rename('MNDWI')
        
        if season == 'Kharif':
            rice_mask = mndwi.gt(0.15).And(ndvi.gt(0.4))
            sugarcane_mask = ndvi.gt(0.65).And(evi.gt(0.5))
            cotton_mask = ndvi.gt(0.45).And(ndvi.lt(0.65)).And(mndwi.lt(0.1))
            crop_colors = ['0066FF', '32CD32', 'FFD700', 'FF4500']
            legend_map = {'Rice': '#0066FF', 'Sugarcane': '#32CD32', 'Cotton/Maize': '#FFD700', 'Other Kharif': '#FF4500'}
        else:
            rice_mask = ndvi.gt(0.55).And(mndwi.lt(0.05))
            sugarcane_mask = ndvi.gt(0.35).And(ndvi.lt(0.55)).And(evi.gt(0.25))
            cotton_mask = ndvi.gt(0.4).And(evi.gt(0.3))
            crop_colors = ['FFD700', '8B4513', 'FFFF00', 'FF4500']
            legend_map = {'Wheat': '#FFD700', 'Barley': '#8B4513', 'Mustard': '#FFFF00', 'Other Rabi': '#FF4500'}
        
        rice_final = rice_mask.And(sugarcane_mask.Not()).And(cotton_mask.Not())
        sugarcane_final = sugarcane_mask.And(rice_mask.Not()).And(cotton_mask.Not())
        cotton_final = cotton_mask.And(rice_mask.Not()).And(sugarcane_mask.Not())
        other_mask = ndvi.gt(0.2).And(rice_final.Not()).And(sugarcane_final.Not()).And(cotton_final.Not())
        
        classification = ee.Image(3)
        classification = classification.where(other_mask, 3)
        classification = classification.where(cotton_final, 2)
        classification = classification.where(sugarcane_final, 1)
        classification = classification.where(rice_final, 0)
        
        def get_crop_area(class_value):
            mask = classification.eq(class_value)
            area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geometry, scale=30, maxPixels=1e9)
            area_info = area.getInfo()
            area_m2 = list(area_info.values())[0] if area_info and area_info.values() else 0
            return float(area_m2 / 1e6) if area_m2 else 0.0
        
        crop1_area = float(get_crop_area(0))
        crop2_area = float(get_crop_area(1))
        crop3_area = float(get_crop_area(2))
        other_area = float(get_crop_area(3))
        
        if season == 'Kharif':
            crops = {'Rice': crop1_area, 'Sugarcane': crop2_area, 'Cotton/Maize': crop3_area, 'Other': other_area}
        else:
            crops = {'Wheat': crop1_area, 'Barley': crop2_area, 'Mustard': crop3_area, 'Other': other_area}
        
        dominant_crop = max(crops, key=crops.get) if max(crops.values()) > 0 else 'Unknown'
        
        classified_vis = classification.visualize(min=0, max=3, palette=crop_colors).clip(geometry)
        classified_url = classified_vis.getMapId()['tile_fetcher'].url_format
        
        time_series_data = generate_time_series(geometry, start_date, end_date, 'NDVI')
        
        # Filter out crops with 0 area from legend
        filtered_legend = {}
        crop_areas = {}
        individual_layers = {}
        
        if season == 'Kharif':
            crop_mapping = {
                'Rice': crop1_area,
                'Sugarcane': crop2_area, 
                'Cotton/Maize': crop3_area,
                'Other Kharif': other_area
            }
            crop_areas = {
                'rice_area': crop1_area,
                'sugarcane_area': crop2_area,
                'cotton_maize_area': crop3_area,
                'other_crops': other_area
            }
            crop_names = ['Rice', 'Sugarcane', 'Cotton/Maize', 'Other Kharif']
        else:
            crop_mapping = {
                'Wheat': crop1_area,
                'Barley': crop2_area,
                'Mustard': crop3_area,
                'Other Rabi': other_area
            }
            crop_areas = {
                'wheat_area': crop1_area,
                'barley_area': crop2_area,
                'mustard_area': crop3_area,
                'other_crops': other_area
            }
            crop_names = ['Wheat', 'Barley', 'Mustard', 'Other Rabi']
        
        # Generate individual crop layers and filter legend - only for crops with area > 0
        for i, crop_name in enumerate(crop_names):
            area = crop_mapping[crop_name]
            if area > 0:  # Only create layer and legend entry if crop has actual area
                filtered_legend[crop_name] = legend_map[crop_name]
                crop_mask = classification.eq(i)
                masked_class = classification.updateMask(crop_mask)
                crop_layer = masked_class.visualize(
                    min=i, max=i, palette=[crop_colors[i], crop_colors[i]]
                ).clip(geometry)
                layer_url = crop_layer.getMapId()['tile_fetcher'].url_format
                individual_layers[crop_name] = layer_url
        
        # Get crop-specific thresholds
        crop_thresholds = get_crop_specific_thresholds(dominant_crop)
        
        # Get weather data
        weather_data = get_weather_data(geometry, start_date, end_date)
        
        response_data = {
            'dominant_crop': dominant_crop,
            'total_crop_area': float(sum(crops.values())),
            'season': season,
            'expected_crops': expected_crops,
            'layers': {
                'classification': classified_url,
                'main_index': classified_url,
                'individual_crops': individual_layers
            },
            'legend': filtered_legend,
            'time_series': time_series_data,
            'health_score': float((sum([crop1_area, crop2_area, crop3_area]) / sum(crops.values()) * 100) if sum(crops.values()) > 0 else 0),
            'crop_thresholds': crop_thresholds,
            'weather': weather_data
        }
        
        response_data.update(crop_areas)
        
        return JsonResponse({
            'success': True,
            'method': f'Seasonal Classification ({season})',
            'data': response_data
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def growth_stage_detection(geometry, start_date, end_date):
    try:
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(geometry)
                     .filterDate(start_date, end_date)
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                     .median())
        
        ndvi = collection.normalizedDifference(['B8', 'B4']).rename('NDVI')
        evi = collection.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': collection.select('B8'), 'RED': collection.select('B4'), 'BLUE': collection.select('B2')}).rename('EVI')
        ndre = collection.normalizedDifference(['B8', 'B5']).rename('NDRE')
        
        # Get NDVI stats to understand the data range
        ndvi_stats = ndvi.reduceRegion(
            reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), '', True),
            geometry=geometry, scale=30, maxPixels=1e9
        ).getInfo()
        print(f"NDVI stats: {ndvi_stats}")
        
        # Use more inclusive thresholds based on actual NDVI distribution
        planting_mask = ndvi.gt(0.05).And(ndvi.lt(0.25))
        vegetative_mask = ndvi.gt(0.25).And(ndvi.lt(0.5))
        flowering_mask = ndvi.gt(0.5).And(ndvi.lt(0.75))
        harvest_mask = ndvi.gt(0.75)
        
        def get_stage_area(mask, stage_name):
            area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geometry, scale=30, maxPixels=1e9)
            area_info = area.getInfo()
            print(f"{stage_name} area info: {area_info}")
            area_value = list(area_info.values())[0] if area_info and area_info.values() else 0
            return float((area_value or 0) / 1e6)
        
        planting_area = float(get_stage_area(planting_mask, "Planting"))
        vegetative_area = float(get_stage_area(vegetative_mask, "Vegetative"))
        flowering_area = float(get_stage_area(flowering_mask, "Flowering"))
        harvest_area = float(get_stage_area(harvest_mask, "Harvest"))
        
        stages = {'Planting': planting_area, 'Vegetative': vegetative_area, 
                 'Flowering': flowering_area, 'Harvest': harvest_area}
        primary_stage = max(stages, key=stages.get) if max(stages.values()) > 0 else 'Unknown'
        
        # Create classification image only for stages with area > 0
        classified = ee.Image(4)  # Default background value
        stage_masks = [planting_mask, vegetative_mask, flowering_mask, harvest_mask]
        stage_areas = [planting_area, vegetative_area, flowering_area, harvest_area]
        
        for i, (mask, area) in enumerate(zip(stage_masks, stage_areas)):
            if area > 0:
                classified = classified.where(mask, i)
        
        stage_colors = ['8B4513', '90EE90', 'FFD700', 'FF4500']
        classified_vis = classified.visualize(min=0, max=3, palette=stage_colors).clip(geometry)
        classified_url = classified_vis.getMapId()['tile_fetcher'].url_format
        
        # Generate individual stage layers and filter legend - only for stages with area > 0
        individual_layers = {}
        stage_names = ['Planting', 'Vegetative', 'Flowering', 'Harvest']
        stage_legend_colors = ['#8B4513', '#90EE90', '#FFD700', '#FF4500']
        filtered_legend = {}
        
        for i, (stage_name, area) in enumerate(zip(stage_names, stage_areas)):
            if area > 0:  # Only create layer and legend entry if stage has actual area
                filtered_legend[stage_name] = stage_legend_colors[i]
                stage_mask = stage_masks[i]
                # Mask classification and visualize with solid color
                masked_class = classified.updateMask(stage_mask)
                stage_layer = masked_class.visualize(
                    min=i, max=i, palette=[stage_colors[i], stage_colors[i]]
                ).clip(geometry)
                layer_url = stage_layer.getMapId()['tile_fetcher'].url_format
                individual_layers[stage_name] = layer_url
        
        time_series_data = generate_time_series(geometry, start_date, end_date, 'NDVI')
        
        response_data = {
            'planting_area': planting_area,
            'vegetative_area': vegetative_area,
            'flowering_area': flowering_area,
            'harvest_area': harvest_area,
            'primary_stage': primary_stage,
            'total_crop_area': float(sum(stages.values())),
            'health_score': float((sum(stage_areas) / (sum(stage_areas) + 0.1) * 100) if sum(stage_areas) > 0 else 0),
            'layers': {
                'classification': classified_url,
                'main_index': classified_url,
                'individual_stages': individual_layers
            },
            'legend': filtered_legend,
            'time_series': time_series_data
        }
        
        return JsonResponse({
            'success': True,
            'data': response_data
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def yield_prediction_analysis(geometry, start_date, end_date):
    try:
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(geometry)
                     .filterDate(start_date, end_date)
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                     .median())
        
        ndvi = collection.normalizedDifference(['B8', 'B4']).rename('NDVI')
        evi = collection.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': collection.select('B8'), 'RED': collection.select('B4'), 'BLUE': collection.select('B2')}).rename('EVI')
        ndmi = collection.normalizedDifference(['B8', 'B11']).rename('NDMI')
        ndre = collection.normalizedDifference(['B8', 'B5']).rename('NDRE')
        
        excellent_mask = evi.gt(0.6).And(ndre.gt(0.2)).And(ndmi.gt(0.1))
        good_mask = evi.gt(0.4).And(evi.lte(0.6)).And(ndre.gt(0.15)).And(ndmi.gt(-0.1))
        average_mask = evi.gt(0.3).And(evi.lte(0.4)).And(ndre.gt(0.1))
        poor_mask = evi.lte(0.3).Or(ndmi.lte(-0.1))
        
        def get_yield_area(mask):
            area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=geometry, scale=30, maxPixels=1e9)
            area_info = area.getInfo()
            print(f"Area info for mask: {area_info}")
            area_value = list(area_info.values())[0] if area_info and area_info.values() else 0
            return float((area_value or 0) / 1e6)
        
        excellent_area = float(get_yield_area(excellent_mask))
        good_area = float(get_yield_area(good_mask))
        average_area = float(get_yield_area(average_mask))
        poor_area = float(get_yield_area(poor_mask))
        
        classified = ee.Image(3).where(excellent_mask, 0).where(good_mask, 1).where(average_mask, 2).where(poor_mask, 3)
        
        stats = ee.Image([ndvi, evi, ndmi, ndre]).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=30, maxPixels=1e9)
        stats_info = stats.getInfo()
        
        evi_val = float(stats_info.get('EVI', 0) or 0)
        ndre_val = float(stats_info.get('NDRE', 0) or 0)
        ndmi_val = float(stats_info.get('NDMI', 0) or 0)
        
        biomass_factor = float(min(1.0, max(0.2, evi_val * 1.5)))
        chlorophyll_factor = float(min(1.0, max(0.3, ndre_val * 3)))
        water_factor = float(1.0 if ndmi_val > 0.1 else (0.8 if ndmi_val > -0.1 else 0.6))
        
        base_yield = float(5.0)
        expected_yield = float(base_yield * biomass_factor * chlorophyll_factor * water_factor)
        
        yield_colors = ['00FF00', '90EE90', 'FFD700', 'FF4500']
        classified_vis = classified.visualize(min=0, max=3, palette=yield_colors).clip(geometry)
        classified_url = classified_vis.getMapId()['tile_fetcher'].url_format
        
        # Generate individual yield layers and filter legend - only for yields with area > 0
        individual_layers = {}
        yield_names = ['Excellent Yield', 'Good Yield', 'Average Yield', 'Poor Yield']
        yield_legend_colors = ['#00FF00', '#90EE90', '#FFD700', '#FF4500']
        yield_masks = [excellent_mask, good_mask, average_mask, poor_mask]
        yield_areas = [excellent_area, good_area, average_area, poor_area]
        filtered_legend = {}
        
        for i, (yield_name, area) in enumerate(zip(yield_names, yield_areas)):
            print(f"Processing {yield_name}: area = {area}")
            if area > 0:  # Only create layer and legend entry if yield category has actual area
                filtered_legend[yield_name] = yield_legend_colors[i]
                yield_mask = yield_masks[i]
                # Mask classification and visualize with solid color
                masked_class = classified.updateMask(yield_mask)
                yield_layer = masked_class.visualize(
                    min=i, max=i, palette=[yield_colors[i], yield_colors[i]]
                ).clip(geometry)
                layer_url = yield_layer.getMapId()['tile_fetcher'].url_format
                individual_layers[yield_name] = layer_url
                print(f"Created layer for {yield_name}: {layer_url[:50]}...")
            else:
                print(f"Skipping {yield_name} - no area detected")
        
        time_series_data = generate_time_series(geometry, start_date, end_date, 'NDVI')
        
        print(f"Final yield areas: Excellent={excellent_area}, Good={good_area}, Average={average_area}, Poor={poor_area}")
        print(f"Individual layers created: {list(individual_layers.keys())}")
        print(f"Filtered legend: {filtered_legend}")
        
        return JsonResponse({
            'success': True,
            'data': {
                'expected_yield': expected_yield,
                'yield_potential': base_yield,
                'excellent_area': excellent_area,
                'good_area': good_area,
                'average_area': average_area,
                'poor_area': poor_area,
                'total_crop_area': float(sum(yield_areas)),
                'health_score': float((biomass_factor + chlorophyll_factor + water_factor) / 3 * 100),
                'layers': {
                    'classification': classified_url,
                    'main_index': classified_url,
                    'individual_yields': individual_layers
                },
                'legend': filtered_legend,
                'time_series': time_series_data
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def crop_specific_analysis(request):
    """Crop-Specific Analysis for Farm Intelligence"""
    if request.method == 'POST':
        data = json.loads(request.body)
        
        roi = data.get('roi')
        start_date = data.get('startDate')
        end_date = data.get('endDate')
        analysis_type = data.get('analysisType')
        season_type = data.get('seasonType', 'auto')
        
        if not initialize_gee():
            return JsonResponse({'success': False, 'error': 'GEE initialization failed'})
        
        try:
            geometry = ee.Geometry(roi['geometry'])
            
            if analysis_type == 'crop_type':
                return crop_type_identification(geometry, start_date, end_date, season_type)
            elif analysis_type == 'growth_stage':
                return growth_stage_detection(geometry, start_date, end_date)
            elif analysis_type == 'yield_prediction':
                return yield_prediction_analysis(geometry, start_date, end_date)
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})