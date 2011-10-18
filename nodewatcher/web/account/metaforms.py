from django.contrib.admin import util as admin_util
from django.forms import forms
from django.forms import models as forms_models

from web.account import utils

class ParentsIncludedModelFormMetaclass(forms_models.ModelFormMetaclass):
  """
  `django.forms.models.ModelFormMetaclass` produces only all declared fields of the current and parent clasess combined with
  fields from the model as defined in `Meta` subclass which is taken from the first class which defines it (as `getattr` finds it).
  This metaclass adds also all other fields of parent classes to the current class.
  
  Workaround for http://code.djangoproject.com/ticket/7018.
  
  It works only on parent classes and not all ancestor classes.
  
  The order of fields could be probably improved. It would be much easier if `django.forms.models.ModelFormMetaclass` would
  simply use `True` in `django.forms.forms.get_declared_fields`.
  
  `Meta` (`self._meta` attribute) is not merged but taken from the first class which defines it (as `getattr` finds it).
  
  Warning: This also means that all `django.forms.models.ModelForm` methods which operate on a model (like `save` and `clean`)
  use only model from the first class which defines it. Use `ParentsIncludedModelFormMixin` for methods which operate also on
  parent `django.forms.models.ModelForm` classes.
  
  It should be used as a `__metaclass__` class of the given multi-parent form class.
  """
  
  def __new__(cls, name, bases, attrs):
    # We store attrs as ModelFormMetaclass.__new__ clears all fields from it
    attrs_copy = attrs.copy()
    new_class = super(ParentsIncludedModelFormMetaclass, cls).__new__(cls, name, bases, attrs)
    # All declared fields + model fields from parent classes
    fields_without_current_model = forms.get_declared_fields(bases, attrs_copy, True)
    new_class.base_fields.update(fields_without_current_model)
    return new_class

class ParentsIncludedModelFormMixin(object):
  """
  When combinining multiple forms based on `django.forms.models.ModelForm` into one form default methods operate only on the
  first object instance (as `getattr` finds it) and also do not allow multiple initial instances to be passed to form
  constructor. This mixin class redefines those methods to operate on multiple instances.
  
  It should be listed as the parent class before `django.forms.models.ModelForm` based classes so that methods here take
  precedence.
  """
  
  def __init__(self, *args, **kwargs):
    """
    Populates `self.instances` and `self.metas` with the given (or constructed empty) instances and `Meta` classes of the current
    and parent (but not all ancestor) classes.
    
    Based on `django.forms.models.BaseModelForm.__init__` method and extended for multiple instances.
    
    Optional `instance` argument should be a list of all instances for the current and parent `django.forms.models.ModelForm`
    classes with defined `Meta` class (with now required `model` attribute).
    """
    
    self.metas = []
    if 'Meta' in self.__class__.__dict__:
      # We add meta of the current class
      self.metas.append(forms_models.ModelFormOptions(self.Meta))
    # We add metas from parent classes
    self.metas += [forms_models.ModelFormOptions(getattr(cls, 'Meta', None)) for cls in self.__class__.__bases__ if issubclass(cls, forms_models.ModelForm)]
    
    instances = kwargs.pop('instance', None)
    if instances is None:
      for meta in self.metas:
        if meta.model is None:
          raise ValueError('ModelForm has no model class specified.')
      self.instances = [meta.model() for meta in self.metas]
      for instance in self.instances:
        instance._adding = True
      object_data = {}
    else:
      self.instances = instances
      for instance in self.instances:
        instance._adding = False
      object_data = {}
      if len(instances) != len(self.metas):
        raise ValueError('Number of instances does not match number of metas.')
      # We traverse in reverse order to keep in sync with get_declared_fields
      for instance, meta in reversed(zip(self.instances, self.metas)):
        object_data.update(forms_models.model_to_dict(instance, meta.fields, meta.exclude))
    
    initial = kwargs.pop('initial', None)
    if initial is not None:
      object_data.update(initial)
    
    super(ParentsIncludedModelFormMixin, self).__init__(initial=object_data, *args, **kwargs)
  
  def _iterate_over_instances(self, method_name, *args, **kwargs):
    """
    Somewhat hackish implementation of a wrapper for multiple instances.
    
    It temporary sets `self.instance` and `self._meta` and calls requested method. It collects possible results of this method calls
    into the list and returns it. At the end it restores `self.instance` and `self._meta` to initial values.
    """
    
    # Save original values
    original_instance = self.instance
    original_meta = self._meta
    
    results = []
    
    for instance, meta in zip(self.instances, self.metas):
      # Temporary set values
      self.instance = instance
      self._meta = meta
      results.append(getattr(super(ParentsIncludedModelFormMixin, self), method_name)(*args, **kwargs))
    
    # Restore original values
    self.instance = original_instance
    self._meta = original_meta
    
    return results
  
  def clean(self):
    # We traverse in reverse order to keep in sync with get_declared_fields
    return reduce(utils.intersect, reversed(self._iterate_over_instances('clean')))
  
  def _post_clean(self):
    self._iterate_over_instances('_post_clean')
  
  # We do not change validate_unique on purpose as it is called from _post_clean and we will probably do not use it otherwise
  
  def save(self, commit=True):
    return self._iterate_over_instances('save', commit)
  
  save.alters_data = True

class FieldsetBoundField(forms.BoundField):
  """
  This class extends `django.forms.forms import.BoundField` to also carry information about the fieldset this field is in.
  """
  
  def __init__(self, form, field, name, fieldset):
    super(FieldsetBoundField, self).__init__(form, field, name)
    self.fieldset = fieldset

class FieldsetFormMixin(object):
  """
  This mixin class defines methods to use with other form classes to extend them to return `FieldsetBoundField` when accessing
  forms' fields. If such form class has `fieldset` attribute defined it is used to attach fieldset to all fields, which
  are returned as `FieldsetBoundField`.
  
  `fieldset` attribute should have the same structure as that for `django.contrib.admin.ModelAdmin`. The attached fieldset is
  the given fieldset dictionary with `name` set to the name of the fieldset.
  
  It should be listed as the parent class before `django.forms.models.ModelForm` based classes so that methods here take
  precedence.
  """
  
  def __iter__(self):
    """
    If `fieldset` attribute is not defined we iterate normally. Otherwise we iterate in the order in which fields
    are defined in `fieldset` attribute. In the later case we return fields as `FieldsetBoundField`.
    """
    
    if not hasattr(self, 'fieldset'):
      for field in super(FieldsetFormMixin, self).__iter__():
        yield field
    else:
      for field in admin_util.flatten_fieldsets(self.fieldset):
        yield self[field]
  
  def __getitem__(self, name):
    """
    If `fieldset` attribute is not defined we return the field normally. Otherwise we return the field as `FieldsetBoundField`
    with fieldset attached to it. It the later case the field has to be defined in `fieldset` attribute.
    """
    
    field = super(FieldsetFormMixin, self).__getitem__(name)
    if not hasattr(self, 'fieldset'):
      return field
    else:
      fieldset = None
      for fname, fset in self.fieldset:
        if name in fset['fields']:
          # We copy dictionary here so that we do not dirty it with later changes
          fieldset = fset.copy()
          fieldset['name'] = fname
          break
      if not fieldset:
        raise KeyError('Key %r not defined in any fieldset in Form' % name)
      return FieldsetBoundField(self, field.field, field.name, fieldset)
