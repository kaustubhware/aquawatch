# 📦 AquaWatch Installation Guide

Complete step-by-step installation guide for end users.

---

## 🎯 Prerequisites

Before you begin, make sure you have:
- **Python 3.8 or higher** installed
- **Git** installed (for Method 1)
- **Google account** for Earth Engine authentication
- **Internet connection**

---

## 📥 Choose Your Download Method

### Method 1: Using Git (Recommended)

```bash
git clone https://github.com/YOUR-USERNAME/aquawatch.git
cd aquawatch
```

### Method 2: Download ZIP

1. Go to the GitHub repository
2. Click green **"Code"** button → **"Download ZIP"**
3. Extract the ZIP file
4. Open Terminal/Command Prompt in the extracted folder

---

## 🛠️ Installation Steps (Same for Both Methods)

### Step 1: Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Authenticate Google Earth Engine

1. **Sign up** (if you haven't): https://earthengine.google.com/
2. **Authenticate:**
   ```bash
   earthengine authenticate
   ```
   - Browser opens → Sign in → Generate Token → Copy code → Paste in terminal

### Step 4: Setup OpenWeather API (Optional)

1. **Get Free API Key:**
   - Go to: https://openweathermap.org/api
   - Sign up → Go to "API keys" tab → Copy your key

2. **Add to Project:**
   - Create `.env` file in project root
   - Add: `OPENWEATHER_API_KEY=your_api_key_here`
   - Save

   **Note:** Weather features work without API key (uses fallback data)

### Step 5: Run Migrations

```bash
python manage.py migrate
```

### Step 6: Start Server

```bash
python manage.py runserver
```

### Step 7: Open Browser

```
http://localhost:8000
```

🎉 **Done!**

---

## 🔄 Running the App After Installation

After the first-time setup, you only need to:

1. **Activate virtual environment**
   
   **Windows:**
   ```bash
   cd path/to/aquawatch
   venv\Scripts\activate
   ```
   
   **Linux/Mac:**
   ```bash
   cd path/to/aquawatch
   source venv/bin/activate
   ```

2. **Start the server**
   ```bash
   python manage.py runserver
   ```

3. **Open browser**
   ```
   http://localhost:8000
   ```

---

## 🐛 Troubleshooting

### Issue: "earthengine: command not found"

**Solution:**
```bash
pip install earthengine-api
earthengine authenticate
```

### Issue: "Earth Engine not initialized"

**Solution:**
1. Run: `earthengine authenticate`
2. Complete the authentication process
3. Restart the Django server

### Issue: "No module named 'ee'"

**Solution:**
```bash
pip install earthengine-api
```

### Issue: Weather data not showing

**Solution:**
- Check if you have added the OpenWeather API key to `.env` file
- Verify the API key is correct
- The app will use fallback data if API key is missing

### Issue: "Port 8000 is already in use"

**Solution:**
Run on a different port:
```bash
python manage.py runserver 8080
```
Then access: `http://localhost:8080`

### Issue: Python not found

**Solution:**
- Make sure Python 3.8+ is installed
- Try using `python3` instead of `python`
- Download Python from: https://www.python.org/downloads/

---

## 📧 Need Help?

If you encounter any issues:
1. Check the troubleshooting section above
2. Open an issue on GitHub
3. Make sure all prerequisites are installed

---

## 🎉 Features Overview

Once installed, you can:
- **Water Analysis**: Monitor water bodies using satellite imagery
- **Farm Analysis**: Analyze crop health and predict yields
- **Weather Analysis**: Get 7-day forecasts and 30-day predictions

---

**Happy Analyzing! 🚀**
