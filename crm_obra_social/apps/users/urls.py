from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('', views.UserListView.as_view(), name='list'),
    path('nuevo/', views.UserCreateView.as_view(), name='create'),
    path('<int:pk>/editar/', views.UserUpdateView.as_view(), name='update'),
    path('perfil/', views.ProfileView.as_view(), name='profile'),
    path('notificaciones/', views.NotificacionListView.as_view(), name='notificaciones'),
    path('notificaciones/leer/', views.NotificacionMarkAllReadView.as_view(), name='notificaciones_leer'),
    path('notificaciones/<int:pk>/leer/', views.NotificacionMarkReadView.as_view(), name='notificacion_leer'),
]
