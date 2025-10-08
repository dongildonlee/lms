"""
URL configuration for core project.

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
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from .views import home_page, login_page, signup_page, dashboard, crypto_page, stocks_page
from accounts import views_analysis
from accounts import views_pages

urlpatterns = [
    path("", home_page, name="home"),
    path("home/", home_page, name="home"),
    path("login/", login_page, name="login"),
    path("signup/", signup_page, name="signup"),
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("dashboard/", dashboard, name="dashboard"),

    # ✅ new canonical crypto route
    path("crypto/", crypto_page, name="crypto"),

    # ♻️ legacy path redirect (safe to remove later)
    path("investments/", RedirectView.as_view(url="/crypto/", permanent=True), name="investments_legacy"),

    path("stocks/", stocks_page, name="stocks"),
    # path("stocks/", views_pages.stocks_page, name="today_stocks"),
        
    path("api/today/update",  views_analysis.api_today_update,  name="api_today_update"),
    path("api/today_stocks",  views_analysis.api_today_stocks,  name="api_today_stocks"),

    #path("stocks-clean/", views_pages.stocks_clean, name="stocks_clean"),

    path("stocks/today/", views_pages.stocks_today, name="stocks_today"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])

