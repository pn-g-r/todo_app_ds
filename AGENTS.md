# AGENTS.md

## Project
Django 6.0 todo app with auth. Python 3.12. SQLite database.

## Commands
```bash
python manage.py runserver          # dev server (127.0.0.1:8000)
python manage.py check              # verify no config errors
python manage.py makemigrations todos  # create migrations
python manage.py migrate            # apply migrations
```

No linter, type checker, or test runner configured.

## Architecture
- `todoproject/` — Django project (settings, root URL conf)
- `todos/` — single app: model + forms + views + templates
- Template base: `todos/templates/todos/base.html` (inline CSS with gradient theme)
- All CSS is inline in `base.html`. No static files or external dependencies.

## Auth
- Uses Django's built-in `User` model and `UserCreationForm`
- Custom register view logs user in immediately after signup
- `LOGIN_URL = "login"`, `LOGIN_REDIRECT_URL = "todo_list"`
- All todo views require login via `LoginRequiredMixin` / `@login_required`

## Key conventions
- Every todo is scoped to `request.user` (queryset filtered in views)
- URLs: `register/`, `login/`, `logout/`, `/` (list), `new/`, `<pk>/edit/`, `<pk>/delete/`
- Class-based views for CRUD, function-based view for register and list
