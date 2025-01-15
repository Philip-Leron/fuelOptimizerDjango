from django.urls import path
from .views import optimize_route

urlpatterns = [
    path('api/optimize-route/', optimize_route, name='optimize_route'),
]
