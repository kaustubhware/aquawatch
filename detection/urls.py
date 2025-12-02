from django.urls import path
from . import views
from . import farm_views
from . import download
from . import crop_analysis
from . import water_views
from . import weather_views
from . import csv_export

urlpatterns = [
    path('', views.home, name='home'),
    path('water-analysis/', views.water_analysis, name='water_analysis'),
    path('farm-analysis/', views.farm_analysis, name='farm_analysis'),
    path('weather-analysis/', views.weather_analysis, name='weather_analysis'),
    path('analyze-farm/', farm_views.analyze_farm_roi, name='analyze_farm_roi'),
    path('preview-index/', farm_views.preview_index, name='preview_index'),
    path('crop-specific-analysis/', crop_analysis.crop_specific_analysis, name='crop_specific_analysis'),
    path('get-download-urls/', download.get_download_urls, name='get_download_urls'),
    path('analyze-water-change/', water_views.analyze_water_change, name='analyze_water_change'),
    path('analyze-seasonal-water/', water_views.analyze_seasonal_water, name='analyze_seasonal_water'),
    path('analyze-water-quality/', water_views.analyze_water_quality, name='analyze_water_quality'),
    path('analyze-advanced-water/', water_views.analyze_advanced_water, name='analyze_advanced_water'),
    path('get-rainfall-forecast/', weather_views.get_rainfall_forecast, name='get_rainfall_forecast'),
    path('download-timeseries-csv/', csv_export.download_timeseries_csv, name='download_timeseries_csv'),
]