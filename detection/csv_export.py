import csv
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

@csrf_exempt
@require_http_methods(["POST"])
def download_timeseries_csv(request):
    try:
        data = json.loads(request.body)
        months = data.get('months', [])
        values = data.get('values', [])
        index_name = data.get('index_name', 'Value')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="timeseries_{index_name}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Date', index_name])
        
        for month, value in zip(months, values):
            writer.writerow([month, value])
        
        return response
    except Exception as e:
        return HttpResponse(f'Error: {str(e)}', status=500)
