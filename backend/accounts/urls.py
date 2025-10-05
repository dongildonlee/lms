from django.urls import path
from .views import signup
from .views_auth import signin
from .views_update import api_get_csv
from . import views_analysis as va
from . import views_data
from .views_analysis import analysis_candles, analysis_cumprofit, analysis_all


urlpatterns = [
    path("signup/", signup, name="signup"),
    path("signin/", signin, name="signin"),
    path("get-csv/", api_get_csv, name="get_csv"),
    path("analysis/candles/<str:symbol_key>/", analysis_candles, name="analysis_candles"),
    path("analysis/cumprofit/<str:symbol_key>/", analysis_cumprofit, name="analysis_cumprofit"),
    path("analysis/all/<str:symbol_key>/", analysis_all, name="analysis_all"),
    path("analysis/jupyter/<str:symbol_key>/", va.analysis_to_jupyter, name="analysis_to_jupyter"),
    path("analysis/check_csv/<str:symbol>/", va.analysis_check_csv, name="analysis_check_csv"),
    path("analysis/fill_csv/<str:symbol>/",  views_data.analysis_fill_csv,  name="analysis_fill_csv"),
    path("analysis/check_historical_csv/<str:symbol>/", va.analysis_check_historical_csv, name="analysis_check_historical_csv"),
    path("analysis/historical/<str:symbol_key>/", va.analysis_historical, name="analysis_historical"),
]
