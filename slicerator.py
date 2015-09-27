from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from six.moves import range
import collections
import itertools
from functools import wraps


class SliceableAttribute(object):
    def __init__(self, slicerator, attribute):
        self._ancestor = slicerator._ancestor
        self._len = slicerator._len
        self._get = attribute
        self._indices = slicerator._indices

    @property
    def indices(self):
        # Advancing indices won't affect this new copy of self._indices.
        indices, self._indices = itertools.tee(iter(self._indices))
        return indices

    def _map_index(self, key):
        if key < -self._len or key >= self._len:
            raise IndexError("Key out of range")
        try:
            abs_key = self._indices[key]
        except TypeError:
            key = key if key >= 0 else self._len + key
            for _, i in zip(range(key + 1), self.indices):
                abs_key = i
        return abs_key

    def __iter__(self):
        return (self._get(i) for i in self.indices)

    def __len__(self):
        return self._len

    def __getitem__(self, key):
        if not (isinstance(key, slice) or
                isinstance(key, collections.Iterable)):
            return self._get(self._map_index(key))
        else:
            rel_indices, new_length = key_to_indices(key, len(self))
            return (self[k] for k in rel_indices)

    __call__ = __getitem__

class Slicerator(object):

    def __init__(self, ancestor, indices=None,
                 length=None, propagated_attrs=None):
        """A generator that supports fancy indexing

        When sliced using any iterable with a known length, it returns another
        object like itself, a Slicerator. When sliced with an integer,
        it returns the data payload.

        Also, the attributes of the parent object can be propagated, exposed
        through the child Slicerators. By default, no attributes are
        propagated. But specific attributes to propagate can be white-listed
        using the optional parameter `propagated_attrs`.

        Class methods taking an index will be remapped if they are decorated
        with `Slicerator.index_attr`. They also have to be present in the
        `propagated_attrs` list.

        Parameters
        ----------
        ancestor : object
        indices : iterable
            Giving indices into `ancestor`.
            Required if len(ancestor) is invalid.
        length : integer
            length of indicies
            This is required if `indices` is a generator,
            that is, if `len(indices)` is invalid
        propagated_attrs : list of str, optional
            list of attributes to be propagated into Slicerator
            Overwrites contents of class propagated_attrs field and decorators.

        Examples
        --------
        # Slicing on a Slicerator returns another Slicerator...
        >>> v = Slicerator([0, 1, 2, 3], range(4), 4)
        >>> v1 = v[:2]
        >>> type(v[:2])
        Slicerator
        >>> v2 = v[::2]
        >>> type(v2)
        Slicerator
        >>> v2[0]
        0
        # ...unless the slice itself has an unknown length, which makes
        # slicing impossible.
        >>> v3 = v2((i for i in [0]))  # argument is a generator
        >>> type(v3)
        generator
        """
        if indices is None and length is None:
            try:
                length = len(ancestor)
                indices = range(length)
            except TypeError:
                raise ValueError("The length parameter is required in this "
                                 "case because len(ancestor) is not valid.")
        elif indices is None:
            indices = range(length)
        elif length is None:
            try:
                length = len(indices)
            except TypeError:
                raise ValueError("The length parameter is required in this "
                                 "case because len(indices) is not valid.")

        # when list of propagated attributes are given explicitly,
        # take this list and ignore the class definition
        if propagated_attrs is not None:
            self.propagated_attrs = propagated_attrs
        else:
            # check propagated_attrs field from the ancestor definition
            if hasattr(ancestor, 'propagated_attrs'):
                self.propagated_attrs = ancestor.propagated_attrs
            else:
                self.propagated_attrs = []

            # add methods having the _propagate hook
            for name in dir(ancestor):
                if hasattr(getattr(ancestor, name), '_propagate'):
                    self.propagated_attrs.append(name)

        self._len = length
        self._ancestor = ancestor
        self._indices = indices
        self._proc_func = lambda image: image

    @classmethod
    def from_func(cls, func, length, propagated_attrs=None):
        """
        Make a Slicerator from a function that accepts an integer index

        Parameters
        ----------
        func : callback
            callable that accepts an integer as its argument
        length : int
            number of elements; used to supposed revserse slicing like [-1]
        propagated_attrs : list, optional
            list of attributes to be propagated into Slicerator
        """
        class Dummy:

            def __getitem__(self, i):
                return func(i)

            def __len__(self):
                return length

        return cls(Dummy(), propagated_attrs=propagated_attrs)

    @classmethod
    def from_class(cls, other_class):
        getitem = other_class.__getitem__
        @wraps(getitem)
        def wrapper(obj, key):
            if isinstance(key, int):
                return getitem(obj, key if key >= 0 else len(obj) + key)
            else:
                indices, new_length = key_to_indices(key, len(obj))
                if new_length is None:
                    return wrapper(obj, (k for k in indices))
                return cls(obj, indices, new_length)

        setattr(other_class, '__getitem__', wrapper)
        setattr(other_class, '_is_slicerator', True)
        return other_class

    @classmethod
    def index_attr(cls, func):
        @wraps(func)
        def wrapper(obj, key, *args, **kwargs):
            indices = key_to_indices(key, len(obj))[0]
            if isinstance(indices, collections.Iterable):
                return (func(obj, i, *args, **kwargs) for i in indices)
            else:
                return func(obj, indices, *args, **kwargs)
        wrapper._indexed = True
        return wrapper

    @classmethod
    def propagate_attr(cls, func):
        func._propagate = True
        return func

    @property
    def indices(self):
        # Advancing indices won't affect this new copy of self._indices.
        indices, self._indices = itertools.tee(iter(self._indices))
        return indices

    def _get(self, key):
        "Wrap ancestor's method in a processing function."
        return self._proc_func(self._ancestor[key])

    def _map_index(self, key):
        if key < -self._len or key >= self._len:
            raise IndexError("Key out of range")
        try:
            abs_key = self._indices[key]
        except TypeError:
            key = key if key >= 0 else self._len + key
            for _, i in zip(range(key + 1), self.indices):
                abs_key = i
        return abs_key

    def __repr__(self):
        msg = "Sliced and/or processed {0}. Original repr:\n".format(
                type(self._ancestor).__name__)
        old = '\n'.join("    " + ln for ln in repr(self._ancestor).split('\n'))
        return msg + old

    def __iter__(self):
        return (self._get(i) for i in self.indices)

    def __len__(self):
        return self._len

    def __getitem__(self, key):
        """for data access"""
        if not (isinstance(key, slice) or
                isinstance(key, collections.Iterable)):
            return self._get(self._map_index(key))
        else:
            rel_indices, new_length = key_to_indices(key, len(self))
            if new_length is None:
                return (self[k] for k in rel_indices)
            indices = _index_generator(rel_indices, self.indices)
            return Slicerator(self._ancestor, indices,
                              new_length, self.propagated_attrs)

    def __getattr__(self, name):
        # to avoid infinite recursion, always check if public field is there
        if 'propagated_attrs' not in self.__dict__:
            self.propagated_attrs = []
        if name in self.propagated_attrs:
            attr = getattr(self._ancestor, name)
            if hasattr(attr, '_indexed'):
                return SliceableAttribute(self, getattr(self._ancestor, name))
            else:
                return getattr(self._ancestor, name)
        raise AttributeError

    def __getstate__(self):
        # When serializing, return a list of the sliced and processed data
        # Any exposed attrs are lost.
        return [self._get(key) for key in self.indices]

    def __setstate__(self, data_as_list):
        # When deserializing, restore the Slicerator
        return self.__init__(data_as_list)


def key_to_indices(key, length):
    if isinstance(key, slice):
        start, stop, step = key.indices(length)
        rel_indices = range(start, stop, step)
        return rel_indices, len(rel_indices)

    if isinstance(key, collections.Iterable):
        # if the input is an iterable, doing 'fancy' indexing
        if hasattr(key, '__array__') and hasattr(key, 'dtype'):
            if key.dtype == bool:
                # if we have a bool array, set up masking but defer
                # the actual computation, returning another Slicerator
                nums = range(length)
                # This next line fakes up numpy's bool masking without
                # importing numpy.
                rel_indices = [x for x, y in zip(nums, key) if y]
                return rel_indices, sum(key)
        try:
            new_length = len(key)
        except TypeError:
            # The key is a generator; return a plain old generator.
            # Without knowing the length of the *key*,
            # we can't give a Slicerator
            # Also it cannot be checked if values are in range.
            gen = ((_k if _k >= 0 else length + _k) for _k in key)
            return gen, None
        else:
            # The key is a list of in-range values. Build another
            # Slicerator, again deferring computation.
            if any(_k < -length or _k >= length for _k in key):
                raise IndexError("Keys out of range")
            rel_indices = ((_k if _k >= 0 else length + _k) for _k in key)
            return rel_indices, new_length

    try:
        # allow negative indexing
        if -length < key < 0:
            return length + key, None
    except TypeError:
        pass

    # in all other case, just return the key and let user handle TypeErrors
    return key, None


def _index_generator(new_indices, old_indices):
    """Find locations of new_indicies in the ref. frame of the old_indices.
    
    Example: (1, 3), (1, 3, 5, 10) -> (3, 10)

    The point of all this trouble is that this is done lazily, returning
    a generator without actually looping through the inputs."""
    # Use iter() to be safe. On a generator, this returns an identical ref.
    new_indices = iter(new_indices)
    n = next(new_indices)
    last_n = None
    done = False
    while True:
        old_indices_, old_indices = itertools.tee(iter(old_indices))
        for i, o in enumerate(old_indices_):
            # If new_indices is not strictly monotonically increasing, break
            # and start again from the beginning of old_indices.
            if last_n is not None and n <= last_n:
                last_n = None
                break
            if done:
                raise StopIteration
            if i == n:
                last_n = n
                try:
                    n = next(new_indices)
                except StopIteration:
                    done = True
                    # Don't stop yet; we still have one last thing to yield.
                yield o
            else:
                continue


def pipeline(func):
    """Decorator to make function aware of Slicerator objects.

    When the function is applied to a Slicerator, it
    returns another lazily-evaluated, Slicerator object.

    When the function is applied to any other object, it falls back on its
    normal behavhior.

    Returns
    -------
    processed_images : Slicerator

    Example
    -------
    Apply the pipeline decorator to your image processing function.
    >>> @pipeline
    ...  def color_channel(image, channel):
    ...      return image[channel, :, :]
    ...

    Passing a Slicerator the function returns another Slicerator
    that "lazily" applies the function when the images come out. Different
    functions can be applied to the same underlying images, creating
    independent objects.
    >>> red_images = color_channel(images, 0)
    >>> green_images = color_channel(images, 1)

    Pipeline functions can also be composed.
    >>> @pipeline
    ... def rescale(image):
    ... return (image - image.min())/image.ptp()
    ...
    >>> rescale(color_channel(images, 0))

    The function can still be applied to ordinary images. The decorator
    only takes affect when a Slicerator object is passed.
    >>> single_img = images[0]
    >>> red_img = red_channel(single_img)  # normal behavior
    """
    @wraps(func)
    def process(obj, *args, **kwargs):
        if hasattr(obj, '_is_slicerator') or isinstance(obj, Slicerator):
            s = Slicerator(obj)
            def f(x):
                return func(x, *args, **kwargs)
            s._proc_func = f
            return s
        else:
            # Fall back on normal behavior of func, interpreting input
            # as a single image.
            return func(obj, *args, **kwargs)

    if process.__doc__ is None:
        process.__doc__ = ''
    process.__doc__ = ("This function has been made lazy. When passed\n"
                       "a Slicerator, it will return a \n"
                       "new Slicerator of the results. When passed \n"
                       "any other objects, its behavior is "
                       "unchanged.\n\n") + process.__doc__
    return process
