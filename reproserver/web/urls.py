"""reproserver URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('about', views.about, name='about'),
    path('unpack', views.unpack, name = 'unpack' ),
    path('reproduce/<provider>/<provider_path>', views.reproduce_provider, name = 'reproduce_provider'),
    path('start_run/<upload_short_id>', views.start_run, name = 'start_run'),
    path('reproduce_local/<upload_short_id>', views.reproduce_local, name = 'reproduce_local'),
]
