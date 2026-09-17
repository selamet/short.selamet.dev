from django.http import HttpResponseNotFound


def verify(request, token):
    return HttpResponseNotFound()
