from django.urls import path,include
from . import views
from rest_framework.routers import DefaultRouter

# router = DefaultRouter()
# router.register(r'conversation/', views.conversation)
# router.register(r'generate/avatar/', views.genate_avatar)

urlpatterns = [
    # path('/', include(router.urls)),
    path('.auth/me/', views.auth_me, name='auth_me'),
    path('.get-csrf-token/', views.get_csrf_token, name='get_csrftoken'),
    path('conversation/', views.conversation, name='conversation'),
    path('generate/avatar/', views.genate_avatar, name='genate_avatar'),

    path('history/ensure/', views.ensure_db),
    path('history/generate/', views.add_conversation),
    path('history/update/', views.update_conversation),
    path('history/delete/', views.delete_conversation),
    path('history/list/', views.list_conversations),
    path('history/read/', views.get_conversation),
    path('history/rename/', views.rename_conversation),
    path('history/delete_all/', views.delete_all_conversations),
    path('history/clear/', views.clear_messages),



    path('getSpeechToken/', views.getSpeechToken, name='getSpeechToken'),
    path('getIceToken/', views.getIceToken, name= 'getIceToken'),
    path('connectAvatar/', views.connectAvatar,name= 'connectAvatar'),
    path('speak/', views.speak),
    path('getSpeakingStatus/', views.getSpeakingStatus),
    path('stopSpeaking/', views.stopSpeaking),
    path('chat/', views.chat),
    path('chat/clearHistory/', views.clearChatHistory),
    path('disconnectAvatar/', views.disconnectAvatar),
    # path('users/<str:user_id>/conversations/', views.ConversationListCreateView.as_view(), name='conversation-list-create'),
    # path('users/<str:user_id>/conversations/<str:conversation_id>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    # path('users/<str:user_id>/conversations/<str:conversation_id>/messages/', views.MessageListCreateView.as_view(), name='message-list-create'),
]
