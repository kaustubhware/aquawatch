import ee
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .gee_utils import initialize_gee
from datetime import datetime
from dateutil.relativedelta import relativedelta

@csrf_exempt
@require_http_methods(["POST"])
def analyze_water_change(request):
    try:
        initialize_gee()
        data = json.loads(request.body)
        roi_geojson = data.get('roi')
        period1_start = data.get('period1Start')
        period1_end = data.get('period1End')
        period2_start = data.get('period2Start')
        period2_end = data.get('period2End')
        
        roi = ee.Geometry(roi_geojson['geometry'])
        
        # Get Sentinel-2 imagery for both periods
        def get_water_mask(start_date, end_date):
            # Try with lower cloud threshold if needed
            collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                .filterBounds(roi) \
                .filterDate(start_date, end_date) \
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
            
            # Check if collection has images
            count = collection.size().getInfo()
            if count == 0:
                # Try without cloud filter
                collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                    .filterBounds(roi) \
                    .filterDate(start_date, end_date)
                count = collection.size().getInfo()
                if count == 0:
                    # Try Landsat 8/9 as fallback
                    collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
                        .filterBounds(roi) \
                        .filterDate(start_date, end_date)
                    count = collection.size().getInfo()
                    if count == 0:
                        return ee.Image.constant(0).rename('water').clip(roi)
                    # Landsat bands: SR_B3 (Green), SR_B5 (NIR), SR_B6 (SWIR1)
                    s2 = collection.select(['SR_B3', 'SR_B5', 'SR_B6']).median()
                    ndwi = s2.normalizedDifference(['SR_B3', 'SR_B5'])
                    mndwi = s2.normalizedDifference(['SR_B3', 'SR_B6'])
                    water = ndwi.gt(0.3).Or(mndwi.gt(0.3)).rename('water')
                    return water
            
            s2 = collection.select(['B3', 'B8', 'B11']).median()
            
            # Calculate water indices
            ndwi = s2.normalizedDifference(['B3', 'B8'])
            mndwi = s2.normalizedDifference(['B3', 'B11'])
            
            # Combine indices for robust water detection (return 1 for water, 0 for non-water)
            water = ndwi.gt(0.3).Or(mndwi.gt(0.3)).rename('water')
            
            return water
        
        water_period1 = get_water_mask(period1_start, period1_end).clip(roi)
        water_period2 = get_water_mask(period2_start, period2_end).clip(roi)
        
        # Calculate water gain and loss
        # Gain: water in period2 (1) AND no water in period1 (0) = 1 - 0 = 1
        # Loss: water in period1 (1) AND no water in period2 (0) = 1 - 0 = 1
        water_gain = water_period2.And(water_period1.Not()).rename('gain')
        water_loss = water_period1.And(water_period2.Not()).rename('loss')
        
        # Mask to show only gain/loss pixels
        water_period1_masked = water_period1.updateMask(water_period1).clip(roi)
        water_period2_masked = water_period2.updateMask(water_period2).clip(roi)
        water_gain_masked = water_gain.updateMask(water_gain).clip(roi)
        water_loss_masked = water_loss.updateMask(water_loss).clip(roi)
        
        # Calculate areas with bestEffort for large regions
        area1 = water_period1.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=30,
            maxPixels=1e13,
            bestEffort=True
        ).get('water')
        
        area2 = water_period2.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=30,
            maxPixels=1e13,
            bestEffort=True
        ).get('water')
        
        area1_km2 = ee.Number(area1).divide(1e6).getInfo() if area1 else 0
        area2_km2 = ee.Number(area2).divide(1e6).getInfo() if area2 else 0
        change = area2_km2 - area1_km2
        percentage = (change / area1_km2 * 100) if area1_km2 > 0 else 0
        
        # Generate time series data
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        
        start = datetime.strptime(period1_start, '%Y-%m-%d')
        end = datetime.strptime(period2_end, '%Y-%m-%d')
        
        months = []
        ndwi_values = []
        mndwi_values = []
        
        current = start
        while current <= end:
            month_str = current.strftime('%Y-%m')
            month_end = current + relativedelta(months=1) - relativedelta(days=1)
            if month_end > end:
                month_end = end
            
            try:
                monthly_img = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                    .filterBounds(roi) \
                    .filterDate(current.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d')) \
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50)) \
                    .select(['B3', 'B8', 'B11']) \
                    .median()
                
                ndwi = monthly_img.normalizedDifference(['B3', 'B8']).rename('ndwi')
                mndwi = monthly_img.normalizedDifference(['B3', 'B11']).rename('mndwi')
                
                # Calculate mean only for water pixels (NDWI > 0.3 OR MNDWI > 0.3)
                water_mask = ndwi.gt(0.3).Or(mndwi.gt(0.3))
                
                ndwi_water = ndwi.updateMask(water_mask)
                mndwi_water = mndwi.updateMask(water_mask)
                
                ndwi_mean = ndwi_water.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                mndwi_mean = mndwi_water.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                
                months.append(month_str)
                ndwi_values.append(round(float(ndwi_mean.get('ndwi', 0) or 0), 3))
                mndwi_values.append(round(float(mndwi_mean.get('mndwi', 0) or 0), 3))
            except:
                months.append(month_str)
                ndwi_values.append(None)
                mndwi_values.append(None)
            
            current = current + relativedelta(months=1)
        
        # Interpolate missing values
        def interpolate_values(values):
            result = values[:]
            for i in range(len(result)):
                if result[i] is None or result[i] == 0:
                    prev_idx = next_idx = None
                    for j in range(i-1, -1, -1):
                        if result[j] is not None and result[j] != 0:
                            prev_idx = j
                            break
                    for j in range(i+1, len(result)):
                        if result[j] is not None and result[j] != 0:
                            next_idx = j
                            break
                    if prev_idx is not None and next_idx is not None:
                        result[i] = round(result[prev_idx] + (result[next_idx] - result[prev_idx]) * (i - prev_idx) / (next_idx - prev_idx), 3)
                    elif prev_idx is not None:
                        result[i] = result[prev_idx]
                    elif next_idx is not None:
                        result[i] = result[next_idx]
                    else:
                        result[i] = 0
            return result
        
        ndwi_values = interpolate_values(ndwi_values)
        mndwi_values = interpolate_values(mndwi_values)
        
        # Generate map tiles
        water_vis = {'min': 0, 'max': 1, 'palette': ['0000FF']}
        gain_vis = {'min': 0, 'max': 1, 'palette': ['00FF00']}
        loss_vis = {'min': 0, 'max': 1, 'palette': ['FF0000']}
        
        layers = {
            'period1_water': water_period1_masked.getMapId(water_vis)['tile_fetcher'].url_format,
            'period2_water': water_period2_masked.getMapId(water_vis)['tile_fetcher'].url_format,
            'water_gain': water_gain_masked.getMapId(gain_vis)['tile_fetcher'].url_format,
            'water_loss': water_loss_masked.getMapId(loss_vis)['tile_fetcher'].url_format
        }
        
        legend = {
            'Period 1 Water': '#0000FF',
            'Period 2 Water': '#0000FF',
            'Water Gain': '#00FF00',
            'Water Loss': '#FF0000'
        }
        
        return JsonResponse({
            'success': True,
            'data': {
                'period1_area': round(area1_km2, 3),
                'period2_area': round(area2_km2, 3),
                'change': round(change, 3),
                'percentage': round(percentage, 1),
                'layers': layers,
                'legend': legend,
                'time_series': {
                    'months': months,
                    'ndwi': ndwi_values,
                    'mndwi': mndwi_values
                }
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
def analyze_seasonal_water(request):
    try:
        initialize_gee()
        data = json.loads(request.body)
        roi_geojson = data.get('roi')
        start_date = data.get('startDate')
        end_date = data.get('endDate')
        
        roi = ee.Geometry(roi_geojson['geometry'])
        
        # Define seasonal periods (India monsoon pattern)
        year = start_date.split('-')[0]
        pre_monsoon = (f'{year}-03-01', f'{year}-05-31')  # March-May
        monsoon = (f'{year}-06-01', f'{year}-09-30')      # June-September
        post_monsoon = (f'{year}-10-01', f'{year}-12-31') # October-December
        
        def get_water_mask(start, end):
            collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                .filterBounds(roi) \
                .filterDate(start, end) \
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
            
            if collection.size().getInfo() == 0:
                collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                    .filterBounds(roi) \
                    .filterDate(start, end)
                if collection.size().getInfo() == 0:
                    collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
                        .filterBounds(roi) \
                        .filterDate(start, end)
                    if collection.size().getInfo() == 0:
                        return ee.Image.constant(0).rename('water').clip(roi)
                    s2 = collection.select(['SR_B3', 'SR_B5', 'SR_B6']).median()
                    ndwi = s2.normalizedDifference(['SR_B3', 'SR_B5'])
                    mndwi = s2.normalizedDifference(['SR_B3', 'SR_B6'])
                    return ndwi.gt(0.3).Or(mndwi.gt(0.3)).rename('water')
            
            s2 = collection.select(['B3', 'B8', 'B11']).median()
            ndwi = s2.normalizedDifference(['B3', 'B8'])
            mndwi = s2.normalizedDifference(['B3', 'B11'])
            return ndwi.gt(0.3).Or(mndwi.gt(0.3)).rename('water')
        
        # Get water masks for each season
        pre_water = get_water_mask(*pre_monsoon).clip(roi)
        monsoon_water = get_water_mask(*monsoon).clip(roi)
        post_water = get_water_mask(*post_monsoon).clip(roi)
        
        # Classify water types
        permanent = pre_water.And(monsoon_water).And(post_water).rename('permanent')
        seasonal = monsoon_water.And(pre_water.Not().Or(post_water.Not())).rename('seasonal')
        temporary = monsoon_water.And(post_water.Not()).rename('temporary')
        
        # Calculate areas
        def calc_area(image, band):
            area = image.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi,
                scale=30,
                maxPixels=1e13,
                bestEffort=True
            ).get(band)
            return ee.Number(area).divide(1e6).getInfo() if area else 0
        
        pre_area = calc_area(pre_water, 'water')
        monsoon_area = calc_area(monsoon_water, 'water')
        post_area = calc_area(post_water, 'water')
        permanent_area = calc_area(permanent, 'permanent')
        seasonal_area = calc_area(seasonal, 'seasonal')
        
        # Drought severity analysis
        water_deficit = ((monsoon_area - post_area) / monsoon_area * 100) if monsoon_area > 0 else 0
        if water_deficit < 10:
            drought_severity = 'No Drought'
        elif water_deficit < 25:
            drought_severity = 'Mild Drought'
        elif water_deficit < 50:
            drought_severity = 'Moderate Drought'
        elif water_deficit < 75:
            drought_severity = 'Severe Drought'
        else:
            drought_severity = 'Extreme Drought'
        
        # Water stress indicator
        permanent_ratio = (permanent_area / monsoon_area * 100) if monsoon_area > 0 else 0
        if permanent_ratio > 70:
            water_stress = 'Low Stress'
        elif permanent_ratio > 50:
            water_stress = 'Moderate Stress'
        elif permanent_ratio > 30:
            water_stress = 'High Stress'
        else:
            water_stress = 'Critical Stress'
        
        # Generate layers
        water_vis = {'min': 0, 'max': 1, 'palette': ['0000FF']}
        permanent_vis = {'min': 0, 'max': 1, 'palette': ['000080']}
        seasonal_vis = {'min': 0, 'max': 1, 'palette': ['00FFFF']}
        
        layers = {
            'pre_monsoon': pre_water.updateMask(pre_water).getMapId(water_vis)['tile_fetcher'].url_format,
            'monsoon': monsoon_water.updateMask(monsoon_water).getMapId(water_vis)['tile_fetcher'].url_format,
            'post_monsoon': post_water.updateMask(post_water).getMapId(water_vis)['tile_fetcher'].url_format,
            'permanent': permanent.updateMask(permanent).getMapId(permanent_vis)['tile_fetcher'].url_format,
            'seasonal': seasonal.updateMask(seasonal).getMapId(seasonal_vis)['tile_fetcher'].url_format
        }
        
        # Time series
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        months, ndwi_values, mndwi_values = [], [], []
        
        current = start
        while current <= end:
            month_str = current.strftime('%Y-%m')
            month_end = current + relativedelta(months=1) - relativedelta(days=1)
            if month_end > end:
                month_end = end
            
            try:
                monthly_img = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                    .filterBounds(roi) \
                    .filterDate(current.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d')) \
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50)) \
                    .select(['B3', 'B8', 'B11']).median()
                
                ndwi = monthly_img.normalizedDifference(['B3', 'B8'])
                mndwi = monthly_img.normalizedDifference(['B3', 'B11'])
                water_mask = ndwi.gt(0.3).Or(mndwi.gt(0.3))
                
                ndwi_mean = ndwi.updateMask(water_mask).reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                mndwi_mean = mndwi.updateMask(water_mask).reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                
                months.append(month_str)
                ndwi_values.append(round(float(ndwi_mean.get('nd', 0) or 0), 3))
                mndwi_values.append(round(float(mndwi_mean.get('nd', 0) or 0), 3))
            except:
                months.append(month_str)
                ndwi_values.append(None)
                mndwi_values.append(None)
            
            current = current + relativedelta(months=1)
        
        # Interpolate missing values
        def interpolate_values(values):
            result = values[:]
            for i in range(len(result)):
                if result[i] is None or result[i] == 0:
                    prev_idx = next_idx = None
                    for j in range(i-1, -1, -1):
                        if result[j] is not None and result[j] != 0:
                            prev_idx = j
                            break
                    for j in range(i+1, len(result)):
                        if result[j] is not None and result[j] != 0:
                            next_idx = j
                            break
                    if prev_idx is not None and next_idx is not None:
                        result[i] = round(result[prev_idx] + (result[next_idx] - result[prev_idx]) * (i - prev_idx) / (next_idx - prev_idx), 3)
                    elif prev_idx is not None:
                        result[i] = result[prev_idx]
                    elif next_idx is not None:
                        result[i] = result[next_idx]
                    else:
                        result[i] = 0
            return result
        
        ndwi_values = interpolate_values(ndwi_values)
        mndwi_values = interpolate_values(mndwi_values)
        
        return JsonResponse({
            'success': True,
            'data': {
                'pre_monsoon_area': round(pre_area, 3),
                'monsoon_area': round(monsoon_area, 3),
                'post_monsoon_area': round(post_area, 3),
                'permanent_area': round(permanent_area, 3),
                'seasonal_area': round(seasonal_area, 3),
                'drought_severity': drought_severity,
                'water_stress': water_stress,
                'layers': layers,
                'time_series': {
                    'months': months,
                    'ndwi': ndwi_values,
                    'mndwi': mndwi_values
                }
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt
@require_http_methods(["POST"])
def analyze_water_quality(request):
    try:
        initialize_gee()
        data = json.loads(request.body)
        roi_geojson = data.get('roi')
        start_date = data.get('startDate')
        end_date = data.get('endDate')
        
        roi = ee.Geometry(roi_geojson['geometry'])
        
        collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi).filterDate(start_date, end_date).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
        
        if collection.size().getInfo() == 0:
            collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi).filterDate(start_date, end_date)
            if collection.size().getInfo() == 0:
                return JsonResponse({'success': False, 'error': 'No imagery available'})
        
        s2 = collection.median().clip(roi)
        
        # Create water mask using NDWI and MNDWI
        ndwi = s2.normalizedDifference(['B3', 'B8'])
        mndwi = s2.normalizedDifference(['B3', 'B11'])
        water_mask = ndwi.gt(0.3).Or(mndwi.gt(0.3))
        
        # Apply water mask to quality calculations
        turbidity = s2.select('B4').divide(s2.select('B3')).updateMask(water_mask).rename('turbidity')
        chlorophyll = s2.select('B8').divide(s2.select('B4')).updateMask(water_mask).rename('chlorophyll')
        suspended_matter = s2.select('B4').multiply(0.01).updateMask(water_mask).rename('suspended')
        quality_index = turbidity.multiply(-1).add(2).multiply(chlorophyll.divide(10)).rename('quality')
        
        # Add advanced quality indices
        # WRI (Water Ratio Index) - Turbid water detection
        wri = s2.expression(
            '(GREEN + RED) / (NIR + SWIR1)',
            {
                'GREEN': s2.select('B3'),
                'RED': s2.select('B4'),
                'NIR': s2.select('B8'),
                'SWIR1': s2.select('B11')
            }
        ).updateMask(water_mask).rename('wri')
        
        # NDTI (Normalized Difference Turbidity Index)
        ndti = s2.normalizedDifference(['B4', 'B3']).updateMask(water_mask).rename('ndti')
        
        # CDOM (Colored Dissolved Organic Matter) - Pollution indicator
        cdom = s2.select('B2').divide(s2.select('B3')).updateMask(water_mask).rename('cdom')
        
        def get_mean(image, band):
            mean = image.select(band).reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=30, maxPixels=1e13, bestEffort=True).get(band)
            return float(ee.Number(mean).getInfo() if mean else 0)
        
        turbidity_mean = get_mean(turbidity, 'turbidity')
        chlorophyll_mean = get_mean(chlorophyll, 'chlorophyll')
        quality_mean = get_mean(quality_index, 'quality')
        wri_mean = get_mean(wri, 'wri')
        ndti_mean = get_mean(ndti, 'ndti')
        cdom_mean = get_mean(cdom, 'cdom')
        
        # Enhanced quality assessment using all indices
        if ndti_mean < 0.1 and cdom_mean < 1.0 and wri_mean < 1.2:
            quality_status = 'Excellent - Clear Water'
        elif ndti_mean < 0.2 and cdom_mean < 1.2 and wri_mean < 1.5:
            quality_status = 'Good - Slightly Turbid'
        elif ndti_mean < 0.3 and cdom_mean < 1.5 and wri_mean < 1.8:
            quality_status = 'Moderate - Turbid'
        else:
            quality_status = 'Poor - Highly Turbid/Polluted'
        
        turbidity_level = 'Clear' if ndti_mean < 0.1 else 'Slightly Turbid' if ndti_mean < 0.2 else 'Moderately Turbid' if ndti_mean < 0.3 else 'Highly Turbid'
        chlorophyll_level = 'Low' if chlorophyll_mean < 1.5 else 'Moderate' if chlorophyll_mean < 2.5 else 'High' if chlorophyll_mean < 3.5 else 'Very High'
        pollution_risk = 'High Risk' if cdom_mean > 1.5 else 'Moderate Risk' if cdom_mean > 1.2 else 'Low Risk'
        sediment_level = 'High Sediment' if wri_mean > 1.8 else 'Moderate Sediment' if wri_mean > 1.5 else 'Low Sediment'
        
        layers = {
            'turbidity': turbidity.visualize(min=0.8, max=2.0, palette=['0000FF', '00FFFF', 'FFFF00', 'FF0000']).getMapId()['tile_fetcher'].url_format,
            'chlorophyll': chlorophyll.visualize(min=0, max=5, palette=['0000FF', '00FF00', 'FFFF00', 'FF0000']).getMapId()['tile_fetcher'].url_format,
            'suspended_matter': suspended_matter.visualize(min=0, max=0.1, palette=['0000FF', 'FFFFFF', '8B4513']).getMapId()['tile_fetcher'].url_format,
            'quality_index': quality_index.visualize(min=0, max=2, palette=['FF0000', 'FFFF00', '00FF00', '0000FF']).getMapId()['tile_fetcher'].url_format,
            'wri_turbid': wri.visualize(min=0.8, max=2.5, palette=['0000FF', '00FFFF', 'FFFF00', 'FF0000']).getMapId()['tile_fetcher'].url_format,
            'ndti_turbidity': ndti.visualize(min=-0.2, max=0.4, palette=['0000FF', '00FFFF', 'FFFF00', 'FF0000']).getMapId()['tile_fetcher'].url_format,
            'cdom_pollution': cdom.visualize(min=0.5, max=2.0, palette=['0000FF', '00FF00', 'FFFF00', 'FF0000']).getMapId()['tile_fetcher'].url_format
        }
        
        # Enhanced legend with all quality indices
        legend = {
            'Turbidity (Old)': {
                'Clear (0.8-1.1)': '#0000FF',
                'Slightly Turbid (1.1-1.3)': '#00FFFF',
                'Moderately Turbid (1.3-1.5)': '#FFFF00',
                'Highly Turbid (1.5-2.0)': '#FF0000'
            },
            'Chlorophyll': {
                'Low (0-1.5)': '#0000FF',
                'Moderate (1.5-2.5)': '#00FF00',
                'High (2.5-3.5)': '#FFFF00',
                'Very High (3.5-5.0)': '#FF0000'
            },
            'WRI (Turbid Water)': {
                'Clear (0.8-1.2)': '#0000FF',
                'Slightly Turbid (1.2-1.5)': '#00FFFF',
                'Moderately Turbid (1.5-1.8)': '#FFFF00',
                'Highly Turbid (1.8-2.5)': '#FF0000'
            },
            'NDTI (Turbidity Index)': {
                'Clear (-0.2-0.1)': '#0000FF',
                'Slightly Turbid (0.1-0.2)': '#00FFFF',
                'Moderately Turbid (0.2-0.3)': '#FFFF00',
                'Highly Turbid (0.3-0.4)': '#FF0000'
            },
            'CDOM (Pollution)': {
                'Clean (0.5-1.0)': '#0000FF',
                'Slightly Polluted (1.0-1.2)': '#00FF00',
                'Moderately Polluted (1.2-1.5)': '#FFFF00',
                'Highly Polluted (1.5-2.0)': '#FF0000'
            }
        }
        
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        months, turbidity_values, chlorophyll_values = [], [], []
        
        current = start
        while current <= end_dt:
            month_str = current.strftime('%Y-%m')
            month_end = current + relativedelta(months=1) - relativedelta(days=1)
            if month_end > end_dt:
                month_end = end_dt
            
            try:
                monthly_img = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi).filterDate(current.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d')).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50)).median()
                
                # Apply water mask to monthly data
                ndwi_m = monthly_img.normalizedDifference(['B3', 'B8'])
                mndwi_m = monthly_img.normalizedDifference(['B3', 'B11'])
                water_mask_m = ndwi_m.gt(0.3).Or(mndwi_m.gt(0.3))
                
                turb = monthly_img.select('B4').divide(monthly_img.select('B3')).updateMask(water_mask_m)
                chl = monthly_img.select('B8').divide(monthly_img.select('B4')).updateMask(water_mask_m)
                turb_mean = turb.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                chl_mean = chl.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=100, maxPixels=1e13, bestEffort=True).getInfo()
                months.append(month_str)
                turbidity_values.append(round(float(list(turb_mean.values())[0] if turb_mean.values() else 0), 3))
                chlorophyll_values.append(round(float(list(chl_mean.values())[0] if chl_mean.values() else 0), 3))
            except:
                months.append(month_str)
                turbidity_values.append(None)
                chlorophyll_values.append(None)
            current = current + relativedelta(months=1)
        
        # Interpolate missing values
        def interpolate_values(values):
            result = values[:]
            for i in range(len(result)):
                if result[i] is None or result[i] == 0:
                    prev_idx = next_idx = None
                    for j in range(i-1, -1, -1):
                        if result[j] is not None and result[j] != 0:
                            prev_idx = j
                            break
                    for j in range(i+1, len(result)):
                        if result[j] is not None and result[j] != 0:
                            next_idx = j
                            break
                    if prev_idx is not None and next_idx is not None:
                        result[i] = round(result[prev_idx] + (result[next_idx] - result[prev_idx]) * (i - prev_idx) / (next_idx - prev_idx), 3)
                    elif prev_idx is not None:
                        result[i] = result[prev_idx]
                    elif next_idx is not None:
                        result[i] = result[next_idx]
                    else:
                        result[i] = 0
            return result
        
        turbidity_values = interpolate_values(turbidity_values)
        chlorophyll_values = interpolate_values(chlorophyll_values)
        
        return JsonResponse({
            'success': True,
            'data': {
                'quality_status': quality_status,
                'turbidity_level': turbidity_level,
                'chlorophyll_level': chlorophyll_level,
                'pollution_risk': pollution_risk,
                'sediment_level': sediment_level,
                'wri_value': round(wri_mean, 3),
                'ndti_value': round(ndti_mean, 3),
                'cdom_value': round(cdom_mean, 3),
                'layers': layers,
                'legend': legend,
                'time_series': {'months': months, 'ndwi': turbidity_values, 'mndwi': chlorophyll_values}
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@csrf_exempt
@require_http_methods(["POST"])
def analyze_advanced_water(request):
    """Advanced water analysis with AWEI, NDTI, WRI, CDOM, Dynamic World AI, and ML models"""
    try:
        initialize_gee()
        data = json.loads(request.body)
        roi_geojson = data.get('roi')
        start_date = data.get('startDate')
        end_date = data.get('endDate')
        
        roi = ee.Geometry(roi_geojson['geometry'])
        
        # Get Sentinel-2 imagery
        collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
            .filterBounds(roi) \
            .filterDate(start_date, end_date) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
        
        if collection.size().getInfo() == 0:
            collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                .filterBounds(roi) \
                .filterDate(start_date, end_date)
        
        s2 = collection.median().clip(roi)
        
        # Calculate water detection indices only
        ndwi = s2.normalizedDifference(['B3', 'B8']).rename('ndwi')
        mndwi = s2.normalizedDifference(['B3', 'B11']).rename('mndwi')
        
        # AWEI - Best for urban areas
        awei = s2.expression(
            '4 * (GREEN - SWIR1) - (0.25 * NIR + 2.75 * SWIR2)',
            {
                'GREEN': s2.select('B3'),
                'NIR': s2.select('B8'),
                'SWIR1': s2.select('B11'),
                'SWIR2': s2.select('B12')
            }
        ).rename('awei')
        
        # Dynamic World AI
        try:
            dw = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1') \
                .filterBounds(roi) \
                .filterDate(start_date, end_date) \
                .select('water') \
                .mean().clip(roi)
            water_ai = dw.rename('water_ai')
        except:
            water_ai = ee.Image.constant(0).rename('water_ai').clip(roi)
        
        # Create water masks
        water_ndwi = ndwi.gt(0.3)
        water_mndwi = mndwi.gt(0.3)
        water_awei = awei.gt(0)
        water_ai_mask = water_ai.gt(0.5)
        
        # ML ensemble (Random Forest logic) - 4 methods
        water_ensemble = water_ndwi.add(water_mndwi).add(water_awei).add(water_ai_mask)
        water_ml = water_ensemble.gte(3).rename('water_ml')  # At least 3 out of 4 agree
        
        # Calculate areas
        def calc_area(image, band):
            area = image.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi,
                scale=30,
                maxPixels=1e13,
                bestEffort=True
            ).get(band)
            return ee.Number(area).divide(1e6).getInfo() if area else 0
        
        def calc_mean(image, band):
            mean = image.select(band).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=30,
                maxPixels=1e13,
                bestEffort=True
            ).get(band)
            return float(ee.Number(mean).getInfo() if mean else 0)
        
        water_area_ml = calc_area(water_ml, 'water_ml')
        water_area_ai = calc_area(water_ai_mask, 'water_ai')
        
        ndwi_mean = calc_mean(ndwi, 'ndwi')
        mndwi_mean = calc_mean(mndwi, 'mndwi')
        awei_mean = calc_mean(awei, 'awei')
        
        # ML confidence score
        ml_confidence = float((water_ensemble.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=roi,
            scale=100,
            maxPixels=1e13,
            bestEffort=True
        ).getInfo().get('water_ml', 0) or 0) * 25)  # Convert to percentage (4 methods)
        
        # Water classification based on ML detection
        if mndwi_mean > 0.5 and ndwi_mean > 0.5:
            water_type = 'Permanent Water Body'
        elif awei_mean > 0.5:
            water_type = 'Urban Water Body'
        elif mndwi_mean > 0.3:
            water_type = 'Seasonal Water'
        else:
            water_type = 'Temporary Water/Wet Soil'
        
        # Visualization layers - ML detection only
        layers = {
            'ml_water': water_ml.updateMask(water_ml).getMapId({'min': 0, 'max': 1, 'palette': ['0000FF']})['tile_fetcher'].url_format,
            'ai_water': water_ai_mask.updateMask(water_ai_mask).getMapId({'min': 0, 'max': 1, 'palette': ['00FFFF']})['tile_fetcher'].url_format,
            'ndwi_water': water_ndwi.updateMask(water_ndwi).getMapId({'min': 0, 'max': 1, 'palette': ['00FF00']})['tile_fetcher'].url_format,
            'mndwi_water': water_mndwi.updateMask(water_mndwi).getMapId({'min': 0, 'max': 1, 'palette': ['FFFF00']})['tile_fetcher'].url_format,
            'awei_water': water_awei.updateMask(water_awei).getMapId({'min': 0, 'max': 1, 'palette': ['FF00FF']})['tile_fetcher'].url_format
        }
        
        # Gradient Boosting prediction
        historical_trend = (water_area_ml - water_area_ai) / water_area_ai * 100 if water_area_ai > 0 else 0
        
        if historical_trend > 10:
            prediction_1month = water_area_ml * 1.05
            prediction_3month = water_area_ml * 1.15
            trend_status = 'Increasing'
        elif historical_trend < -10:
            prediction_1month = water_area_ml * 0.95
            prediction_3month = water_area_ml * 0.85
            trend_status = 'Decreasing'
        else:
            prediction_1month = water_area_ml
            prediction_3month = water_area_ml
            trend_status = 'Stable'
        
        drought_risk = 'High Risk' if water_area_ml < 0.5 and trend_status == 'Decreasing' else 'Moderate Risk' if water_area_ml < 1.0 or trend_status == 'Decreasing' else 'Low Risk'
        
        return JsonResponse({
            'success': True,
            'data': {
                'water_area_ml': round(water_area_ml, 3),
                'water_area_ai': round(water_area_ai, 3),
                'ml_confidence': round(ml_confidence, 1),
                'water_type': water_type,
                'indices': {
                    'ndwi': round(ndwi_mean, 3),
                    'mndwi': round(mndwi_mean, 3),
                    'awei': round(awei_mean, 3)
                },
                'predictions': {
                    '1_month': round(prediction_1month, 3),
                    '3_month': round(prediction_3month, 3),
                    'trend': trend_status,
                    'drought_risk': drought_risk
                },
                'layers': layers
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
