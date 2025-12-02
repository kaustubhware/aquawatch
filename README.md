# AquaWatch - AI-Powered Satellite Analysis Platform

AquaWatch is a comprehensive satellite imagery analysis platform powered by Google Earth Engine, providing real-time insights for water resources, agriculture, and weather monitoring.

## 🌟 Features

### 🌊 Water Analysis
- Water body detection and monitoring
- Seasonal water availability tracking
- Change detection over time
- Water quality assessment
- Time series analysis

### 🌾 Farm & Crop Analysis
- **Basic Vegetation Health**: NDVI, EVI, NDMI, VCI indices
- **Crop Type Identification**: ML-based classification (Kharif/Rabi seasons)
- **Growth Stage Detection**: Phenological stage monitoring
- **Yield Prediction**: Crop yield forecasting
- Seasonal crop mapping (Rice, Wheat, Sugarcane, Cotton, etc.)

### 🌤️ Weather Analysis
- 7-day weather forecast
- 30-day rainfall prediction
- Historical weather trends
- Smart recommendations for farming and water management

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Google Earth Engine account
- pip package manager

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/YOUR-USERNAME/aquawatch.git
cd aquawatch
```

2. **Create virtual environment**
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Authenticate Google Earth Engine**
   ```bash
   earthengine authenticate
   ```
   Follow the browser prompts to authenticate with your Google account

5. **Run migrations**
```bash
python manage.py migrate
```

6. **Start the server**
```bash
python manage.py runserver
```

7. **Access the application**
Open your browser and navigate to: `http://localhost:8000`

## 📁 Project Structure

```
Project/
├── detection/              # Main Django app
│   ├── views.py           # Water analysis views
│   ├── farm_views.py      # Farm analysis views
│   ├── weather_views.py   # Weather analysis views
│   ├── crop_analysis.py   # Crop-specific analysis
│   ├── gee_utils.py       # Google Earth Engine utilities
│   └── urls.py            # URL routing
├── templates/             # HTML templates
│   ├── home.html         # Landing page
│   ├── water_analysis.html
│   ├── farm_analysis.html
│   └── weather_analysis.html
├── water_detection/       # Django project settings
├── manage.py
└── requirements.txt
```

## 🛠️ Technology Stack

- **Backend**: Django 4.x
- **Satellite Data**: Google Earth Engine
- **Frontend**: HTML5, CSS3, JavaScript
- **Mapping**: Leaflet.js with drawing tools
- **Charts**: Chart.js
- **Satellite Imagery**: Sentinel-2, ERA5, CHIRPS

## 📊 Data Sources

- **Sentinel-2**: 10m resolution multispectral imagery
- **ERA5**: Weather and climate data
- **CHIRPS**: Rainfall estimates
- **MODIS**: Land surface temperature

## 🎯 Usage

### Water Analysis
1. Navigate to Water Analysis
2. Draw ROI (Region of Interest) on the map or upload shapefile
3. Select date range
4. Choose analysis type (Basic, Seasonal, Change Detection)
5. Click "Analyze Water Bodies"

### Farm Analysis
1. Navigate to Farm Analysis
2. Draw farm boundary on the map
3. Select crop year and season (Kharif/Rabi)
4. Choose analysis type
5. Click "Analyze Farm Health"

### Weather Analysis
1. Navigate to Weather Analysis
2. Select location on map
3. View 7-day forecast and 30-day predictions
4. Access historical weather data

## 🔑 Configuration

### Google Earth Engine Setup

1. **Sign up for Google Earth Engine**
   - Go to [Google Earth Engine](https://earthengine.google.com/)
   - Sign up with your Google account
   - Wait for approval (usually instant for non-commercial use)

2. **Authenticate**
   ```bash
   earthengine authenticate
   ```
   - A browser window will open
   - Sign in with your Google account
   - Copy the authorization code
   - Paste it back in the terminal
   - Credentials are saved locally in `~/.config/earthengine/`

3. **Verify Authentication**
   ```bash
   python manage.py runserver
   ```
   The app should now work with your authenticated credentials!

## 📝 Features in Detail

### Vegetation Indices
- **NDVI**: Normalized Difference Vegetation Index
- **EVI**: Enhanced Vegetation Index
- **NDMI**: Normalized Difference Moisture Index
- **VCI**: Vegetation Condition Index

### Crop Classification
- **Kharif Season** (June-October): Rice, Sugarcane, Cotton, Maize
- **Rabi Season** (November-April): Wheat, Barley, Mustard, Gram
- ML-based classification with 85-90% accuracy

### Export Options
- GeoTIFF downloads (10m resolution)
- CSV time series data
- Interactive visualizations

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Common Issues

**Issue**: "Earth Engine not initialized"
- **Solution**: 
  - Run `earthengine authenticate` in terminal
  - Follow the authentication prompts
  - Verify your GEE account is approved at https://earthengine.google.com/
  - Restart the Django server after authentication

**Issue**: "No data available for selected region"
- **Solution**: Ensure the date range has available Sentinel-2 imagery (post-2015)

**Issue**: Map not loading
- **Solution**: Check internet connection and browser console for errors

## 📧 Support

For issues and questions, please open an issue on the repository.

## 🙏 Acknowledgments

- Google Earth Engine for satellite data access
- Sentinel-2 mission for high-resolution imagery
- Open-source community for amazing tools and libraries

---

**Built with ❤️ using Google Earth Engine and Django**
