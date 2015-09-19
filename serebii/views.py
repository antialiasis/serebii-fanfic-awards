import json
from django.shortcuts import render
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.views.generic.base import View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView, CreateView
from django.core.urlresolvers import reverse, reverse_lazy
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, login
from serebii.models import User, Member, Fic
from serebii.forms import VerificationForm, RegisterForm, UserLookupForm, PasswordResetForm


class JSONViewMixin(object):
    """
    Add to a form view to enable AJAX JSON responses.

    """
    def render_to_json_response(self, context, **response_kwargs):
        data = json.dumps(context)
        response_kwargs['content_type'] = 'application/json'
        return HttpResponse(data, **response_kwargs)


class RegisterView(CreateView):
    template_name = "register.html"
    form_class = RegisterForm
    success_url = reverse_lazy('verification')

    def form_valid(self, form):
        response = super(RegisterView, self).form_valid(form)
        user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
        login(self.request, user)
        return response


class VerificationView(FormView):
    template_name = "verification.html"
    form_class = VerificationForm
    success_url = reverse_lazy('home')

    def get_form_kwargs(self):
        kwargs = super(VerificationView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        self.request.user.member = form.member
        self.request.user.verified = True
        self.request.user.save()
        messages.success(self.request, u"You have been successfully verified as %s! You can change your Biography profile field on the forums back now, if you like." % form.member)
        return super(VerificationView, self).form_valid(form)


class PasswordResetLookupView(FormView):
    template_name = "password_reset_lookup.html"
    form_class = UserLookupForm

    def get_success_url(self):
        return reverse('reset_password', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        self.object = form.user
        self.object.verification_code = User.objects.make_random_password()
        self.object.save()
        return super(PasswordResetLookupView, self).form_valid(form)


class PasswordResetView(SingleObjectMixin, FormView):
    model = User
    template_name = "password_reset.html"
    form_class = PasswordResetForm
    success_url = reverse_lazy('home')
    context_object_name = 'reset_user'

    def dispatch(self, *args, **kwargs):
        self.object = self.get_object()
        return super(PasswordResetView, self).dispatch(*args, **kwargs)

    def get_queryset(self):
        return User.objects.filter(verified=True, member__isnull=False)

    def get_form_kwargs(self):
        kwargs = super(PasswordResetView, self).get_form_kwargs()
        kwargs['user'] = self.object
        return kwargs

    def form_valid(self, form):
        user = form.save()
        messages.success(self.request, u"Your password has been successfully reset! You can change your Biography profile field on the forums back now, if you like.")
        response = super(PasswordResetView, self).form_valid(form)
        user = authenticate(username=user.username, password=form.cleaned_data['password1'])
        login(self.request, user)
        return response


class SerebiiObjectLookupView(JSONViewMixin, View):
    model = None

    def get_object(self):
        try:
            url = self.request.GET.get('url')
        except KeyError:
            return None

        page_class = self.model.get_page_class()

        try:
            params = page_class.get_params_from_url(url)
        except ValueError:
            return None
        return self.model.from_params(save=True, **params)
        
    def get(self, *args, **kwargs):
        try:
            self.object = self.get_object()
        except ValidationError as e:
            context = {'error': e.message}
        else:
            if isinstance(self.object, Fic):
                other_objects = [{'type': 'nominee', 'pk': author.pk, 'name': unicode(author), 'object': {'username': author.username}} for author in self.object.authors.all()]
            else:
                other_objects = []
            if self.object is None:
                context = {'error': u"Lookup failed. Please double-check that you entered a valid URL."}
            else:
                context = {'pk': self.object.pk, 'name': unicode(self.object), 'object': {'title': self.object.title, 'authors': [author.pk for author in self.object.authors.all()]}, 'other_objects': other_objects}
        return self.render_to_json_response(context)