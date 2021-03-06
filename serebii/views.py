import json
from django.shortcuts import redirect, render
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.views.generic.base import View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView, CreateView, UpdateView
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from awards.models import verify_current, Phase, CURRENT_YEAR
from serebii.models import User, Member, Fic
from serebii.forms import VerificationForm, RegisterForm, UserInfoForm, UserLookupForm, PasswordResetForm


class UnverifiedUserMiddleware:
    """
    Check if the current user is an unverified temp user and if there
    is a verified user for the same member. If so, log the user out.

    This prevents unverified users from sneaking in to override a
    verified user's votes.

    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if (
                request.user.is_authenticated and
                request.user.member and
                not request.user.verified and
                User.objects.filter(member=request.user.member, verified=True).exists()
            ):
                logout(request)
                return redirect(reverse('login'))

        return self.get_response(request)


class JSONViewMixin(object):
    """
    Add to a form view to enable AJAX JSON responses.

    """
    def render_to_json_response(self, context, **response_kwargs):
        data = json.dumps(context)
        response_kwargs['content_type'] = 'application/json'
        return HttpResponse(data, **response_kwargs)


class LoginRequiredMixin(object):
    """
    A mixin to make views require login.

    """
    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(LoginRequiredMixin, self).dispatch(*args, **kwargs)


class RegisterView(CreateView):
    template_name = "register.html"
    form_class = RegisterForm
    success_url = reverse_lazy('verification')

    def form_valid(self, form):
        response = super(RegisterView, self).form_valid(form)
        user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
        login(self.request, user)
        return response


class EditUserInfoView(LoginRequiredMixin, UpdateView):
    template_name = "edit_user_info.html"
    model = User
    form_class = UserInfoForm
    success_url = reverse_lazy('edit_user_info')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, u"Your information has been successfully edited!")
        response = super().form_valid(form)
        # Make sure the user doesn't get logged out
        update_session_auth_hash(self.request, self.object)
        return response


class VerificationView(LoginRequiredMixin, FormView):
    template_name = "verification.html"
    form_class = VerificationForm
    success_url = reverse_lazy('home')

    def get_form_kwargs(self):
        kwargs = super(VerificationView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        phase = Phase.get_current()
        if phase == 'nomination':
            kwargs['has_unverified'] = self.request.session.get('unverified_nominations_%s' % CURRENT_YEAR, False)
        elif phase == 'voting':
            kwargs['has_unverified'] = self.request.session.get('unverified_votes_%s' % CURRENT_YEAR, False)
        else:
            kwargs['has_unverified'] = False
        return kwargs

    def form_valid(self, form):
        self.request.user.member = form.member
        self.request.user.verified = True
        self.request.user.save()
        if form.made_unverified or form.cleaned_data.get('verify_current'):
            verify_current(form.member)
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

    def get_page(self):
        try:
            url = self.request.GET['url']
        except KeyError:
            return None

        page_class = self.model.get_page_class()

        try:
            params = page_class.get_params_from_url(url)
        except ValueError:
            return None
        return page_class.from_params(save=True, object_type=self.request.GET.get('type'), **params)

    def get(self, *args, **kwargs):
        try:
            page = self.get_page()
        except ValidationError as e:
            context = {'error': e.message}
        else:
            obj = page.object
            if isinstance(obj, Fic):
                other_objects = [author.to_dict() for author in obj.authors.all()]
            else:
                other_objects = []

            if obj is None:
                context = {'error': u"Lookup failed. Please double-check that you entered a valid URL."}
            else:
                context = obj.to_dict()
                context['other_objects'] = other_objects
        return self.render_to_json_response(context)
