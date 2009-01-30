from copy import deepcopy

from django import forms
from django.db import models
from django.utils.datastructures import SortedDict
from django.utils.text import capfirst

from filter.filters import Filter, CharFilter, BooleanFilter, ChoiceFilter

def get_declared_filters(bases, attrs, with_base_filters=True):
    filters = []
    for filter_name, obj in attrs.items():
        if isinstance(obj, Filter):
            obj = attrs.pop(filter_name)
            obj.name = filter_name
            filters.append((filter_name, obj))
    filters.sort(key=lambda x: x[1].creation_counter)
    
    if with_base_filters:
        for base in bases[::-1]:
            if hasattr(base, 'base_filters'):
                filters = base.base_filters.items() + filters
    else:
        for base in bases[::-1]:
            if hasattr(base, 'declared_filters'):
                filters = base.declared_fields.items() + filters
    
    return SortedDict(filters)

def filters_for_model(model, fields=None, exclude=None, filter_for_field=None):
    field_list = []
    opts = model._meta
    for f in opts.fields + opts.many_to_many:
        if fields and f.name not in fields:
            continue
        if exclude and f.name in exclude:
            continue
        filter_ = filter_for_field(f, f.name)
        if filter_:
            field_list.append((f.name, filter_))
    return SortedDict(field_list)

class FilterSetOptions(object):
    def __init__(self, options=None):
        self.model = getattr(options, 'model', None)
        self.fields = getattr(options, 'fields', None)
        self.exclude = getattr(options, 'exclude', None)

class FilterSetMetaclass(type):
    def __new__(cls, name, bases, attrs):
        try:
            parents = [b for b in bases if issubclass(b, FilterSet)]
        except NameError:
            # We are defining FilterSet itself here
            parents = None
        declared_filters = get_declared_filters(bases, attrs, False)
        new_class = super(FilterSetMetaclass, cls).__new__(cls, name, bases, attrs)
        
        if not parents:
            return new_class
        
        opts = new_class._meta = FilterSetOptions(getattr(new_class, 'Meta', None))
        if opts.model:
            filters = filters_for_model(opts.model, opts.fields, opts.exclude, new_class.filter_for_field)
            filters.update(declared_filters)
        else:
            filters = declared_filters
        
        new_class.declared_filters = declared_filters
        new_class.base_filters = filters
        return new_class

FILTER_FOR_DBFIELD_DEFAULTS = {
    models.CharField: CharFilter,
    models.BooleanField: BooleanFilter,
}

class BaseFilterSet(object):
    filter_overrides = {}
    
    def __init__(self, data=None, queryset=None):
        self.data = data or {}
        self.queryset = queryset
        
        self.filters = deepcopy(self.base_filters)
            
    def __iter__(self):
        for obj in self.qs:
            yield obj
    
    @property
    def qs(self):
        if not hasattr(self, '_qs'):            
            qs = self.queryset.all()
            for name, filter_ in self.filters.iteritems():
                try:
                    val = self.form.fields[name].clean(self.form[name].data)
                    if val:
                        qs = filter_.filter(qs, val)
                except forms.ValidationError:
                    pass
            self._qs = qs
        return self._qs
    
    @property
    def form(self):
        if not hasattr(self, '_form'):
            fields = SortedDict([(f[0], f[1].field) for f in self.filters.iteritems()])
            Form =  type('%sForm' % self.__class__.__name__, (forms.Form,), fields)
            self._form = Form(self.data)
        return self._form
        
    @classmethod
    def filter_for_field(cls, f, name):
        filter_for_field = dict(FILTER_FOR_DBFIELD_DEFAULTS, **cls.filter_overrides)
        
        if f.choices:
            return ChoiceFilter(name=name, label=capfirst(f.verbose_name), choices=f.choices)

        filter_ = filter_for_field.get(f.__class__)
        if filter_ is not None:
            return filter_(name=name, label=capfirst(f.verbose_name))

class FilterSet(BaseFilterSet):
    __metaclass__ = FilterSetMetaclass
    
