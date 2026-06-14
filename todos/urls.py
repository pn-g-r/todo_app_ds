from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("", views.todo_list, name="todo_list"),
    path("new/", views.TodoCreateView.as_view(), name="todo_create"),
    path("<int:pk>/edit/", views.TodoUpdateView.as_view(), name="todo_update"),
    path("<int:pk>/delete/", views.TodoDeleteView.as_view(), name="todo_delete"),
    path("profile/", views.profile_view, name="profile"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
