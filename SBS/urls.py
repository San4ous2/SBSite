"""
URL configuration for SB_Site project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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

from django.urls import path
from . import views

urlpatterns = [
    # Main pages
    path('', views.home, name='home'),
    path('documentation/', views.documentation, name='documentation'),
    path('privacy/', views.privacy, name='privacy'),

    # Test pages
    path('test/', views.test_view, name='test'),
    path('test/basic/', views.basic_test_view, name='test_basic'),

    # PDF Export
    path('export/pdf/basic/', views.export_pdf_basic, name='export_pdf_basic'),
    path('export/pdf/pro/', views.export_pdf_pro, name='export_pdf_pro'),

    # PDF Downloads
    path('pdf/download/<path:filename>/', views.download_pdf, name='download_pdf'),

    # Payment
    path('payment/create-checkout-session/', views.create_checkout_session, name='create_checkout_session'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('payment/webhook/', views.stripe_webhook, name='stripe_webhook'),
]
