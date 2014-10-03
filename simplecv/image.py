from cStringIO import StringIO
from operator import itemgetter
import cStringIO
import os
import re
import tempfile
import time
from simplecv.core.drawing.renderer import Renderer

try:
    from PIL import Image as PilImage
except:
    import Image as PilImage

import cv2
import numpy as np

from simplecv import exif
from simplecv.base import logger, ScvException, on_ipython_notebook
from simplecv.color import Color
from simplecv.core.image import cached_method
from simplecv.core.image import convert
from simplecv.core.image import Image as CoreImage
from simplecv.core.image.loader import ImageLoader
from simplecv.core.pluginsystem import apply_plugins
from simplecv.display import Display
from simplecv.core.drawing.layer import DrawingLayer
from simplecv.features.features import FeatureSet
from simplecv.stream import JpegStreamer, VideoStream


@apply_plugins
class Image(CoreImage):
    """
    **SUMMARY**

    The Image class is the heart of SimpleCV and allows you to convert to and
    from a number of source types with ease.  It also has intelligent buffer
    management, so that modified copies of the Image required for algorithms
    such as edge detection, etc can be cached and reused when appropriate.


    Image are converted into 8-bit, 3-channel images in RGB colorspace.
    It will automatically handle conversion from other representations into
    this standard format.  If dimensions are passed, an empty image is created.

    **EXAMPLE**

    >>> i = Image("/path/to/image.png")
    >>> c = Camera().get_image()


    You can also just load the SimpleCV logo using:

    >>> img = Image("simplecv")
    >>> img2 = Image("logo")
    >>> img3 = Image("logo_inverted")
    >>> img4 = Image("logo_transparent")

    Or you can load an image from a URL:

    >>> img = Image("http://www.simplecv.org/image.png")

    """

    def __new__(cls, source=None, **kwargs):
        filename = None
        if isinstance(source, np.ndarray):
            ndarray = source
            color_space = kwargs.get('color_space')
        elif 'array' in kwargs:
            ndarray = kwargs['array']
            color_space = kwargs.get('color_space')
        else:
            if 'source' not in kwargs:
                kwargs['source'] = source
            ndarray, color_space, filename = ImageLoader.load(**kwargs)
        obj = CoreImage.__new__(cls, ndarray, color_space)
        obj.filename = filename
        return obj

    def __init__(self, source=None, **kwargs):
        super(Image, self).__init__(array=source, color_space=kwargs.get('color_space'))
        self.camera = kwargs.get('camera')

    def __array_finalize__(self, obj):
        super(Image, self).__array_finalize__(obj)

        ### DEFAULT VALUES ###
        # Keypoint Descriptors
        self._key_points = []
        self._kp_descriptors = []
        self._kp_flavor = None
        # Pallete Stuff
        self._do_hue_palette = False
        self._palette_bins = None
        self._palette = None
        self._palette_members = None
        self._palette_percentages = None
        # Temp files
        self._temp_files = []
        # drawing layers
        self.layers = []
        # to store grid details | Format -> [gridIndex, gridDimensions]
        self._grid_layer = [None, [0, 0]]
        # Other
        self.camera = getattr(obj, 'camera', None)  # self.camera is unused so far
        self.filename = None
        self.filehandle = None
        # The variables uncropped_x and uncropped_y are used to buffer the
        # points when we crop the image.
        self.uncropped_x = 0
        self.uncropped_y = 0

    # def __getstate__(self):
    #     return dict(color_space=self._color_space,
    #                 array=self.apply_layers())
    #
    # def __setstate__(self, d):
    #     self.__init__(**d)

    def save(self, filehandle_or_filename="", mode="", verbose=False,
             temp=False, path=None, filename=None, clean_temp=False, **params):
        """
        **SUMMARY**

        Save the image to the specified filename.  If no filename is provided
        then it will use the filename the Image was loaded from or the last
        place it was saved to. You can save to lots of places, not just files.
        For example you can save to the Display, a JpegStream, VideoStream,
        temporary file, or Ipython Notebook.


        Save will implicitly render the image's layers before saving, but the
        layers are
        not applied to the Image itself.


        **PARAMETERS**

        * *filehandle_or_filename* - the filename to which to store the file.
         The method will infer the file type.

        * *mode* - This flag is used for saving using pul.

        * *verbose* - If this flag is true we return the path where we saved
         the file.

        * *temp* - If temp is True we save the image as a temporary file and
         return the path

        * *path* - path where temporary files needed to be stored

        * *filename* - name(Prefix) of the temporary file.

        * *clean_temp* - This flag is made True if tempfiles are tobe deleted
         once the object is to be destroyed.

        * *params* - This object is used for overloading the PIL save methods.
          In particular this method is useful for setting the jpeg compression
          level. For JPG see this documentation:
          http://www.pythonware.com/library/pil/handbook/format-jpeg.htm

        **EXAMPLES**

        To save as a temporary file just use:

        >>> img = Image('simplecv')
        >>> img.save(temp=True)

        It will return the path that it saved to.

        Save also supports IPython Notebooks when passing it a Display object
        that has been instainted with the notebook flag.

        To do this just use::

          >>> disp = Display(displaytype='notebook')
          >>> img.save(disp)

        .. Note::
          You must have IPython notebooks installed for this to work path and
          filename are valid if and only if temp is set to True.

        .. attention::
          We need examples for all save methods as they are unintuitve.

        """
        #TODO, we use the term mode here when we mean format
        #TODO, if any params are passed, use PIL

        if temp:
            import glob

            if filename is None:
                filename = 'Image'
            if path is None:
                path = tempfile.gettempdir()
            if glob.os.path.exists(path):
                path = glob.os.path.abspath(path)
                imagefiles = glob.glob(
                    glob.os.path.join(path, filename + "*.png"))
                num = [0]
                for img in imagefiles:
                    num.append(int(glob.re.findall('[0-9]+$', img[:-4])[-1]))
                num.sort()
                fnum = num[-1] + 1
                filename = glob.os.path.join(
                    path, filename + ("%07d" % fnum) + ".png")
                self._temp_files.append((filename, clean_temp))
                self.save(self._temp_files[-1][0])
                return self._temp_files[-1][0]
            else:
                print "Path does not exist!"
                return None

        else:
            if filename:
                filehandle_or_filename = filename + ".png"

        if not filehandle_or_filename:
            if self.filename:
                filehandle_or_filename = self.filename
            else:
                filehandle_or_filename = self.filehandle

        if len(self.layers):
            saveimg = self.apply_layers()
        else:
            saveimg = self

        if self._color_space != Image.BGR \
                and self._color_space != Image.GRAY:
            saveimg = saveimg.to_bgr()

        if not isinstance(filehandle_or_filename, basestring):

            fh = filehandle_or_filename

            if isinstance(fh, JpegStreamer):
                fh.jpgdata = StringIO()
                saveimg.get_pil().save(
                    fh.jpgdata, "jpeg",
                    **params)  # save via PIL to a StringIO handle
                fh.refreshtime = time.time()
                self.filename = ""
                self.filehandle = fh

            elif isinstance(fh, VideoStream):
                self.filename = ""
                self.filehandle = fh
                fh.write_frame(saveimg)

            elif isinstance(fh, Display):
                #self.filename = ""
                self.filehandle = fh
                fh.write_frame(saveimg)

            else:
                if not mode:
                    mode = "jpeg"

                try:
                     # The latest version of PIL / PILLOW supports webp,
                     # try this first, if not gracefully fallback
                    saveimg.get_pil().save(fh, mode, **params)
                     # set the filename for future save operations
                    self.filehandle = fh
                    self.filename = ""
                    return 1
                except Exception, e:
                    if mode.lower() != 'webp':
                        raise e

            if verbose:
                print self.filename

            if not mode.lower() == 'webp':
                return 1

        #make a temporary file location if there isn't one
        if not filehandle_or_filename:
            filename = tempfile.mkstemp(suffix=".png")[-1]
        else:
            filename = filehandle_or_filename

        #allow saving in webp format
        if mode == 'webp' or re.search('\.webp$', filename):
            try:
                #newer versions of PIL support webp format, try that first
                self.get_pil().save(filename, **params)
            except:
                # if PIL doesn't support it, maybe we have
                # the python-webm library
                try:
                    from webm import encode as webm_encode
                    from webm.handlers import BitmapHandler, WebPHandler
                except:
                    logger.warning(
                        'You need the webm library to save to webp format. '
                        'You can download from: '
                        'https://github.com/sightmachine/python-webm')
                    return 0

                #PNG_BITMAP_DATA = bytearray(
                #   Image.open(PNG_IMAGE_FILE).tostring())
                png_bitmap_data = bytearray(self.to_string())
                image_width = self.width
                image_height = self.height

                image = BitmapHandler(
                    png_bitmap_data, BitmapHandler.RGB,
                    image_width, image_height, image_width * 3
                )
                result = webm_encode.EncodeRGB(image)

                if isinstance(filehandle_or_filename, cStringIO.InputType):
                    filehandle_or_filename.write(result.data)
                else:
                    file(filename.format("RGB"), "wb").write(result.data)
                return 1
        # if the user is passing kwargs use the PIL save method.
        # usually this is just the compression rate for the image
        if params:
            if not mode:
                mode = "jpeg"
            saveimg.get_pil().save(filename, mode, **params)
            return 1

        if filename:
            if self.is_gray():
                cv2.imwrite(filename, saveimg)
            else:
                cv2.imwrite(filename, saveimg.to_bgr())

            # set the filename for future save operations
            self.filename = filename
            self.filehandle = ""
        elif self.filename:
            if self.is_gray():
                cv2.imwrite(filename, saveimg)
            else:
                cv2.imwrite(filename, saveimg.to_bgr())
        else:
            return 0

        if verbose:
            print self.filename

        if temp:
            return filename
        else:
            return 1

    def delete_temp_files(self):
        for fname, cleanup in self._temp_files:
            if cleanup:
                os.remove(fname)

    def add_drawing_layer(self, layer=None):
        """
        **SUMMARY**

        Push a new drawing layer onto the back of the layer stack

        **PARAMETERS**

        * *layer* - The new drawing layer to add.

        **RETURNS**

        The index of the new layer as an integer.

        **EXAMPLE**

        >>> img = Image("Lenna")
        >>> myLayer = DrawingLayer()
        >>> img.add_drawing_layer(myLayer)

        **SEE ALSO**

        :py:class:`DrawingLayer`
        :py:meth:`dl`
        :py:meth:`get_drawing_layer`
        :py:meth:`clear_layers`
        :py:meth:`merged_layers`
        :py:meth:`apply_layers`
        """
        if layer is None:
            layer = DrawingLayer()

        if not isinstance(layer, DrawingLayer):
            raise ScvException("Please pass a DrawingLayer object")

        self.layers.append(layer)
        return len(self.layers) - 1

    def apply_layers(self, indicies=None, renderer='cv2'):
        """
        **SUMMARY**

        Render all of the layers onto the current image and return the result.
        Indicies can be a list of integers specifying the layers to be used.

        **PARAMETERS**

        * *indicies* -  Indicies can be a list of integers specifying the
         layers to be used.

        **RETURNS**

        The image after applying the drawing layers.

        **EXAMPLE**

        >>> img = Image("Lenna")
        >>> myLayer1 = DrawingLayer()
        >>> myLayer2 = DrawingLayer()
        >>> #Draw some stuff
        >>> img.insert_drawing_layer(myLayer1, 1) # on top
        >>> img.insert_drawing_layer(myLayer2, 2) # on the bottom
        >>> derp = img.apply_layers()

        **SEE ALSO**

        :py:class:`DrawingLayer`
        :py:meth:`dl`
        :py:meth:`get_drawing_layer`
        """
        if len(self.layers) == 0:
            self.add_drawing_layer()

        if indicies is None:
            merged_layer = self.merged_layers()
        else:
            layers = itemgetter(*indicies)(self.layers)
            merged_layer = reduce(lambda a, b: a + b, layers)

        # preform drawing
        return Renderer.render(merged_layer, self.copy(), renderer=renderer)

    def get_drawing_layer(self, index=-1):
        """
        **SUMMARY**

        Return a drawing layer based on the provided index.  If not provided,
        will default to the top layer.  If no layers exist, one will be created

        **PARAMETERS**

        * *index* - returns the drawing layer at the specified index.

        **RETURNS**

        A drawing layer.

        **EXAMPLE**

        >>> img = Image("Lenna")
        >>> myLayer1 = DrawingLayer()
        >>> myLayer2 = DrawingLayer()
        >>> #Draw on the layers
        >>> img.insert_drawing_layer(myLayer1,1) # on top
        >>> img.insert_drawing_layer(myLayer2,2) # on the bottom
        >>> layer2 =img.get_drawing_layer(2)

        **SEE ALSO**

        :py:class:`DrawingLayer`
        :py:meth:`dl`
        :py:meth:`get_drawing_layer`
        :py:meth:`clear_layers`
        :py:meth:`merged_layers`
        :py:meth:`apply_layers`
        """
        if not len(self.layers):
            layer = DrawingLayer()
            self.add_drawing_layer(layer)
        return self.layers[index]

    def dl(self, index=-1):
        """
        **SUMMARY**

        Alias for :py:meth:`get_drawing_layer`

        """
        return self.get_drawing_layer(index)

    def clear_layers(self):
        """
        **SUMMARY**

        Remove all of the drawing layers.

        **RETURNS**

        None.

        **EXAMPLE**

        >>> img = Image("Lenna")
        >>> myLayer1 = DrawingLayer()
        >>> myLayer2 = DrawingLayer()
        >>> img.insert_drawing_layer(myLayer1,1) # on top
        >>> img.insert_drawing_layer(myLayer2,2) # on the bottom
        >>> img.clear_layers()

        **SEE ALSO**

        :py:class:`DrawingLayer`
        :py:meth:`dl`
        :py:meth:`get_drawing_layer`
        :py:meth:`merged_layers`
        :py:meth:`apply_layers`
        """
        self.layers = []

    def merged_layers(self):
        """
        **SUMMARY**

        Return all DrawingLayer objects as a single DrawingLayer.

        **RETURNS**

        Returns a drawing layer with all of the drawing layers of this image
        merged into one.

        **EXAMPLE**

        >>> img = Image("Lenna")
        >>> myLayer1 = DrawingLayer()
        >>> myLayer2 = DrawingLayer()
        >>> img.insert_drawing_layer(myLayer1,1) # on top
        >>> img.insert_drawing_layer(myLayer2,2) # on the bottom
        >>> derp = img.merged_layers()

        **SEE ALSO**

        :py:class:`DrawingLayer`
        :py:meth:`add_drawing_layer`
        :py:meth:`dl`
        :py:meth:`get_drawing_layer`
        :py:meth:`apply_layers`
        """
        return reduce(lambda a, b: a + b, self.layers)

    @cached_method
    def get_pil(self):
        """
        **SUMMARY**

        Get a PIL Image object for use with the Python Image Library
        This is handy for some PIL functions.

        **RETURNS**

        Returns the Python Imaging Library (PIL) version of this image.

        **EXAMPLE**

        >>> img = Image("lenna")
        >>> rawImg  = img.get_pil()

        **SEE ALSO**

        :py:meth:`get_empty`
        :py:meth:`get_bitmap`
        :py:meth:`get_matrix`
        :py:meth:`get_fp_matrix`
        :py:meth:`get_numpy`
        :py:meth:`get_gray_numpy`
        :py:meth:`get_grayscale_matrix`
        """
        return convert.to_pil_image(self)

    @cached_method
    def get_pg_surface(self):
        """
        **SUMMARY**

        Returns the image as a pygame surface.  This is used for rendering the
        display

        **RETURNS**

        A pygame surface object used for rendering.
        """
        return convert.to_pg_surface(self)

    def get_exif_data(self):
        """
        **SUMMARY**

        This function extracts the exif data from an image file like JPEG or
        TIFF. The data is returned as a dict.

        **RETURNS**

        A dictionary of key value pairs. The value pairs are defined in the
        exif.py file.

        **EXAMPLE**

        >>> img = Image("./SimpleCV/data/sampleimages/OWS.jpg")
        >>> data = img.get_exif_data()
        >>> data['Image GPSInfo'].values

        **NOTES**

        * Compliments of: http://exif-py.sourceforge.net/

        * See also: http://en.wikipedia.org/wiki/Exchangeable_image_file_format

        **See Also**

        :py:class:`EXIF`
        """
        if len(self.filename) < 5 or self.filename is None:
            # I am not going to warn, better of img sets
            # logger.warning("ImageClass.get_exif_data: This image did not come
            # from a file, can't get EXIF data.")
            return {}

        file_name, file_extension = os.path.splitext(self.filename)
        file_extension = file_extension.lower()
        if file_extension != '.jpeg' and file_extension != '.jpg' \
                and file_extension != 'tiff' and file_extension != '.tif':
            return {}

        raw = open(self.filename, 'rb')
        data = exif.process_file(raw)
        return data

    def draw_features(self, features, color=Color.GREEN, width=1, autocolor=False):
        """
        **SUMMARY**

        This is a method to draw Features on any given image.

        **PARAMETERS**

        * *features* - FeatureSet or any Feature
         (eg. Line, Circle, Corner, etc)
        * *color*    - Color of the Feature to be drawn
        * *width*    - width of the Feature to be drawn
        * *autocolor*- If true a color is randomly selected for each feature

        **RETURNS**
        None

        **EXAMPLE**

        img = Image("lenna")
        lines = img.equalize().find_lines()
        img.draw(lines)
        img.show()
        """
        if isinstance(features, Image):
            logger.warn("You need to pass drawable features.")
            return
        if hasattr(features, 'draw'):
            from copy import deepcopy

            if isinstance(features, FeatureSet):
                cfeatures = deepcopy(features)
                for cfeat in cfeatures:
                    cfeat.image = self
                cfeatures.draw(color, width, autocolor)
            else:
                cfeatures = deepcopy(features)
                cfeatures.image = self
                cfeatures.draw(color, width)
        else:
            logger.warn("You need to pass drawable features.")

    def show(self, type='window'):
        """
        **SUMMARY**

        This function automatically pops up a window and shows the current
        image.

        **PARAMETERS**

        * *type* - this string can have one of two values, either 'window', or
         'browser'. Window opens a display window, while browser opens the
         default web browser to show an image.

        **RETURNS**

        This method returns the display object. In the case of the window this
        is a JpegStreamer object. In the case of a window a display
        object is returned.

        **EXAMPLE**

        >>> img = Image("lenna")
        >>> img.show()
        >>> img.show('browser')

        **SEE ALSO**

        :py:class:`JpegStreamer`
        :py:class:`Display`

        """
        if type == 'browser':
            import webbrowser

            js = JpegStreamer(8080)
            self.save(js)
            webbrowser.open("http://localhost:8080", 2)
            return js
        elif type == 'window':
            from simplecv.display import Display

            if on_ipython_notebook():
                from IPython.display import SVG
                return SVG(data=self.apply_layers(renderer='svg'))
            else:
                d = Display(self.size_tuple)
                self.save(d)
                return d
        else:
            logger.warning("Unknown type to show")

    def draw_keypoint_matches(self, template, thresh=500.00, min_dist=0.15,
                              width=1):
        """
        **SUMMARY**

        Draw keypoints draws a side by side representation of two images,
        calculates keypoints for both images, determines the keypoint
        correspondences, and then draws the correspondences. This method is
        helpful for debugging keypoint calculations and also looks really
        cool :) The parameters mirror the parameters used for
        findKeypointMatches to assist with debugging

        **PARAMETERS**

        * *template* - A template image.
        * *quality* - The feature quality metric. This can be any value between
          about 300 and 500. Higher values should return fewer, but higher
          quality features.
        * *min_dist* - The value below which the feature correspondence is
          considered a match. This is the distance between two feature vectors
          Good values are between 0.05 and 0.3
        * *width* - The width of the drawn line.

        **RETURNS**

        A side by side image of the template and source image with each feature
        correspondence draw in a different color.

        **EXAMPLE**

        >>> img = cam.getImage()
        >>> template = Image("myTemplate.png")
        >>> result = img.draw_keypoint_matches(self,template,300.00,0.4):

        **NOTES**

        If you would prefer to work with the raw keypoints and descriptors each
        image keeps a local cache of the raw values. These are named:

        self._key_points # A tuple of keypoint objects
        See: http://opencv.itseez.com/modules/features2d/doc/
        common_interfaces_of_feature_detectors.html#keypoint-keypoint
        self._kp_descriptors # The descriptor as a floating point numpy array
        self._kp_flavor = "NONE" # The flavor of the keypoints as a string.

        **SEE ALSO**

        :py:meth:`draw_keypoint_matches`
        :py:meth:`find_keypoints`
        :py:meth:`find_keypoint_match`

        """
        if template is None:
            return None

        result_img = template.side_by_side(self, scale=False)
        hdif = (self.height - template.height) / 2
        skp, sd = self._get_raw_keypoints(thresh)
        tkp, td = template._get_raw_keypoints(thresh)
        if td is None or sd is None:
            logger.warning("We didn't get any descriptors. Image might be too "
                           "uniform or blurry.")
            return result_img
        template_points = float(td.shape[0])
        sample_points = float(sd.shape[0])
        magic_ratio = 1.00
        if sample_points > template_points:
            magic_ratio = float(sd.shape[0]) / float(td.shape[0])
        # match our keypoint descriptors
        idx, dist = self._get_flann_matches(sd, td)
        p = dist[:, 0]
        result = p * magic_ratio < min_dist
        for i in range(0, len(idx)):
            if result[i]:
                pt_a = (tkp[i].pt[0], tkp[i].pt[1] + hdif)
                pt_b = (skp[idx[i]].pt[0] + template.width, skp[idx[i]].pt[1])
                result_img.dl().line(pt_a, pt_b, color=Color.get_random(),
                                     width=width)
        return result_img

    def draw_palette_colors(self, size=(-1, -1), horizontal=True, bins=10,
                            hue=False):
        """
        **SUMMARY**

        This method returns the visual representation (swatches) of the palette
        in an image. The palette is orientated either horizontally or
        vertically, and each color is given an area proportional to the number
        of pixels that have that color in the image. The palette is arranged as
        it is returned from the clustering algorithm. When size is left
        to its default value, the palette size will match the size of the
        orientation, and then be 10% of the other dimension. E.g. if our image
        is 640X480 the horizontal palette will be (640x48) likewise the
        vertical palette will be (480x64)

        If a Hue palette is used this method will return a grayscale palette.

        **PARAMETERS**

        * *bins* - an integer number of bins into which to divide the colors in
          the image.
        * *hue* - if hue is true we do only cluster on the image hue values.
        * *size* - The size of the generated palette as a (width,height) tuple,
          if left default we select
          a size based on the image so it can be nicely displayed with the
          image.
        * *horizontal* - If true we orientate our palette horizontally,
         otherwise vertically.

        **RETURNS**

        A palette swatch image.

        **EXAMPLE**

        >>> p = img1.draw_palette_colors()
        >>> img2 = img1.side_by_side(p, side="bottom")
        >>> img2.show()

        **NOTES**

        The hue calculations should be siginificantly faster than the generic
        RGB calculation as it works in a one dimensional space. Sometimes the
        underlying scipy method freaks out about k-means initialization with
        the following warning:

        .. Warning::
          One of the clusters is empty. Re-run kmean with a different
          initialization. This shouldn't be a real problem.

        **SEE ALSO**

        :py:meth:`re_palette`
        :py:meth:`draw_palette_colors`
        :py:meth:`palettize`
        :py:meth:`get_palette`
        :py:meth:`binarize_from_palette`
        :py:meth:`find_blobs_from_palette`

        """
        self.generate_palette(bins, hue)
        ret_val = None
        if not hue:
            if horizontal:
                if size[0] == -1 or size[1] == -1:
                    size = (int(self.width), int(self.height * .1))
                pal = np.zeros((size[1], size[0], 3), dtype=np.uint8)
                idx_l = 0
                idx_h = 0
                for i in range(0, min(bins, self._palette.shape[0])):
                    idx_h = np.clip(
                        idx_h +
                        (self._palette_percentages[i] * float(size[0])),
                        0, size[0] - 1)
                    roi = (int(idx_l), 0, int(idx_h - idx_l), size[1])
                    roiimage = pal[roi[1]:roi[1] + roi[3],
                                   roi[0]:roi[0] + roi[2]]
                    color = np.array((
                        float(self._palette[i][2]),
                        float(self._palette[i][1]),
                        float(self._palette[i][0])))
                    roiimage += color
                    pal[roi[1]:roi[1] + roi[3],
                        roi[0]:roi[0] + roi[2]] = roiimage
                    idx_l = idx_h
                ret_val = Image(pal)
            else:
                if size[0] == -1 or size[1] == -1:
                    size = (int(self.width * .1), int(self.height))
                pal = np.zeros((size[1], size[0], 3), dtype=np.uint8)
                idx_l = 0
                idx_h = 0
                for i in range(0, min(bins, self._palette.shape[0])):
                    idx_h = np.clip(
                        idx_h + self._palette_percentages[i] * size[1], 0,
                        size[1] - 1)
                    roi = (0, int(idx_l), size[0], int(idx_h - idx_l))
                    roiimage = pal[roi[1]:roi[1] + roi[3],
                                   roi[0]:roi[0] + roi[2]]
                    color = np.array((
                        float(self._palette[i][2]),
                        float(self._palette[i][1]),
                        float(self._palette[i][0])))
                    roiimage += color
                    pal[roi[1]:roi[1] + roi[3],
                        roi[0]:roi[0] + roi[2]] = roiimage
                    idx_l = idx_h
                ret_val = Image(pal)
        else:  # do hue
            if horizontal:
                if size[0] == -1 or size[1] == -1:
                    size = (int(self.width), int(self.height * .1))
                pal = np.zeros((size[1], size[0], 3), dtype=np.uint8)
                idx_l = 0
                idx_h = 0
                for i in range(0, min(bins, self._palette.shape[0])):
                    idx_h = np.clip(
                        idx_h +
                        (self._palette_percentages[i] * float(size[0])),
                        0, size[0] - 1)
                    roi = (int(idx_l), 0, int(idx_h - idx_l), size[1])
                    roiimage = pal[roi[1]:roi[1] + roi[3],
                                   roi[0]:roi[0] + roi[2]]
                    roiimage += self._palette[i]
                    pal[roi[1]:roi[1] + roi[3],
                        roi[0]:roi[0] + roi[2]] = roiimage
                    idx_l = idx_h
                ret_val = Image(pal)
            else:
                if size[0] == -1 or size[1] == -1:
                    size = (int(self.width * .1), int(self.height))
                pal = np.zeros((size[1], size[0], 3), dtype=np.uint8)
                idx_l = 0
                idx_h = 0
                for i in range(0, min(bins, self._palette.shape[0])):
                    idx_h = np.clip(
                        idx_h + self._palette_percentages[i] * size[1], 0,
                        size[1] - 1)
                    roi = (0, int(idx_l), size[0], int(idx_h - idx_l))
                    roiimage = pal[roi[1]:roi[1] + roi[3],
                                   roi[0]:roi[0] + roi[2]]
                    roiimage += self._palette[i]
                    pal[roi[1]:roi[1] + roi[3],
                        roi[0]:roi[0] + roi[2]] = roiimage
                    idx_l = idx_h
                ret_val = Image(pal)
        return ret_val

    def grid(img, dimensions=(10, 10), color=(0, 0, 0), width=1,
             antialias=True, alpha=-1):
        """
        **SUMMARY**

        Draw a grid on the image

        **PARAMETERS**

        * *dimensions* - No of rows and cols as an (rows,xols) tuple or list.
        * *color* - Grid's color as a tuple or list.
        * *width* - The grid line width in pixels.
        * *antialias* - Draw an antialiased object
        * *aplha* - The alpha blending for the object. If this value is -1 then
          the layer default value is used. A value of 255 means opaque, while
          0 means transparent.

        **RETURNS**

        Returns the index of the drawing layer of the grid

        **EXAMPLE**

        >>>> img = Image('something.png')
        >>>> img.grid([20, 20], (255, 0, 0))
        >>>> img.grid((20, 20), (255, 0, 0), 1, True, 0)
        """
        ret_val = img.copy()
        try:
            step_row = img.size_tuple[1] / dimensions[0]
            step_col = img.size_tuple[0] / dimensions[1]
        except ZeroDivisionError:
            return None

        i = 1
        j = 1

        grid = DrawingLayer()  # add a new layer for grid
        while (i < dimensions[0]) and (j < dimensions[1]):
            if i < dimensions[0]:
                grid.line((0, step_row * i), (img.size_tuple[0], step_row * i),
                          color, width, antialias, alpha)
                i = i + 1
            if j < dimensions[1]:
                grid.line((step_col * j, 0), (step_col * j, img.size_tuple[1]),
                          color, width, antialias, alpha)
                j = j + 1
        # store grid layer index
        ret_val._grid_layer[0] = ret_val.add_drawing_layer(grid)
        ret_val._grid_layer[1] = dimensions
        return ret_val

    def remove_grid(img):
        """
        **SUMMARY**

                Remove Grid Layer from the Image.

        **PARAMETERS**

                None

        **RETURNS**

                Drawing Layer corresponding to the Grid Layer

        **EXAMPLE**

        >>>> img = Image('something.png')
        >>>> img.grid([20,20],(255,0,0))
        >>>> gridLayer = img.remove_grid()

        """

        if img._grid_layer[0] is not None:
            grid = img.remove_drawing_layer(img._grid_layer[0])
            img._grid_layer = [None, [0, 0]]
            return grid
        else:
            return None

    def draw_sift_key_point_match(self, template, distance=200, num=-1,
                                  width=1):
        """
        **SUMMARY**

        Draw SIFT keypoints draws a side by side representation of two images,
        calculates keypoints for both images, determines the keypoint
        correspondences, and then draws the correspondences. This method is
        helpful for debugging keypoint calculations and also looks really
        cool :) The parameters mirror the parameters used for
        findKeypointMatches to assist with debugging

        **PARAMETERS**

        * *template* - A template image.
        * *distance* - This can be any value between about 100 and 500. Lower
                       value should return less number of features but higher
                       quality features.
        * *num* -   Number of features you want to draw. Features are sorted
                    according to the dist from min to max.
        * *width* - The width of the drawn line.

        **RETURNS**

        A side by side image of the template and source image with each feature
        correspondence draw in a different color.

        **EXAMPLE**

        >>> cam = Camera()
        >>> img = cam.get_image()
        >>> template = Image("myTemplate.png")
        >>> result = img.draw_sift_key_point_match(template, 300.00):

        **SEE ALSO**

        :py:meth:`draw_keypoint_matches`
        :py:meth:`find_keypoints`
        :py:meth:`find_keypoint_match`

        """
        if template is None:
            return
        result_img = template.side_by_side(self, scale=False)
        hdif = (self.height - template.height) / 2
        sfs, tfs = self.match_sift_key_points(template, distance)
        maxlen = min(len(sfs), len(tfs))
        if num < 0 or num > maxlen:
            num = maxlen
        for i in range(num):
            skp = sfs[i]
            tkp = tfs[i]
            pt_a = (int(tkp.x), int(tkp.y) + hdif)
            pt_b = (int(skp.x) + template.width, int(skp.y))
            #pt_a = (int(tkp.y), int(tkp.x) + hdif)
            #pt_b = (int(skp.y) + template.width, int(skp.x))
            result_img.dl().line(pt_a, pt_b, color=Color.get_random(),
                                 width=width)
        return result_img

    def find(self, feature_class, *args, **kwargs):
        return feature_class.find(self, *args, **kwargs)
