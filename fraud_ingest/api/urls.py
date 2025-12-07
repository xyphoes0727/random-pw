from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter
from . import views
from . import consumers
from rest_framework_simplejwt.views import (
    TokenObtainPairView, TokenRefreshView)

router = DefaultRouter()

router.register(
    r'transactions',
    views.EnrichedTransactionViewSet,
    basename='enriched-transaction'
)

router.register(
    r'predictions',
    views.MLPredictionViewSet,
    basename='ml-prediction'
)

websocket_urlpatterns = [
    re_path(r'ws/transactions/$', consumers.TransactionConsumer.as_asgi()),
]

urlpatterns = [
    path(
        "stats/",
        views.GlobalStatsAPIView.as_view(),
        name="global-stats",
    ),
    path(
        "shap/values/",
        views.ShapValuesView.as_view(),
        name="shap-values",
    ),
    path(
        "",
        include(router.urls),
    ),
    path(
        "transaction_details/",
        views.get_transaction_details,
        name="transaction-details",
    ),
    path(
        "feedback/",
        views.KafkaProducerView.as_view(),
        name="submit-feedback",
    ),
    path(
        "metrics/",
        views.ConfusionMatrixAPI.as_view(),
        name="metrics-api",
    ),
    path(
        "token/",
        TokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "token/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),
    path(
        "register/",
        views.UserRegistrationView.as_view(),
        name="user_register",
    ),
    path(
        "chat/",
        views.ChatBotView.as_view(),
        name="chat_api"
    ),
    path(
        "chat/update",
        views.ConversationManagementView.as_view(),
        name="clear_conversation"
    ),
    path(
        'send_email/',
        views.SendEmailAPIView.as_view(),
        name='send_email'
    ),
    path(
        'transaction_analysis/',
        views.TransactionRelatedDataToHelpAnalyst.as_view(),
        name='transaction_analysis'
    ),
    path(
        'llm_reanalysis/',
        views.LLMReanalyserAPIView.as_view(),
        name='llm_reanalysis'
    ),
    path(
        "model-health/",
        views.ModelHealthAPIView.as_view(),
        name="model_health"
        ),
    path(
        'health/',
        views.HealthCheckAPIView.as_view(),
        name='health_check'
        ),
]
