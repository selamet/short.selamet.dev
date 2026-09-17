def workspace(request):
    """Expose the current workspace and the user's memberships to the app shell."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    memberships = user.memberships.select_related("workspace").order_by("workspace__name")
    return {"current_workspace": getattr(request, "workspace", None), "memberships": memberships}
