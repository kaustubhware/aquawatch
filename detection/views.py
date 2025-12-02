from django.shortcuts import render

def home(request):
    return render(request, 'home.html')

def farm_analysis(request):
    return render(request, 'farm_analysis.html')

def water_analysis(request):
    return render(request, 'water_analysis.html')

def weather_analysis(request):
    return render(request, 'weather_analysis.html')
