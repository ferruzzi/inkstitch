# Authors: see git history
#
# Copyright (c) 2010 Authors
# Licensed under the GNU GPL version 3.0 or later.  See the file LICENSE for details.

import os
import sys
import tempfile
from copy import deepcopy
from zipfile import ZipFile

from lxml import etree

import pyembroidery
from inkex import Boolean

from ..i18n import _
from ..output import write_embroidery_file
from ..stitch_plan import stitch_groups_to_stitch_plan
from ..threads import ThreadCatalog
from ..svg import PIXELS_PER_MM
from ..utils.geometry import Point
from .base import InkstitchExtension


class Zip(InkstitchExtension):
    def __init__(self, *args, **kwargs):
        InkstitchExtension.__init__(self)

        # it's kind of obnoxious that I have to do this...
        self.formats = []
        for format in pyembroidery.supported_formats():
            if 'writer' in format and format['category'] in ['embroidery', 'color', 'image', 'stitch']:
                extension = format['extension']
                self.arg_parser.add_argument('--format-%s' % extension, type=Boolean, dest=extension)
                self.formats.append(extension)
        self.arg_parser.add_argument('--format-svg', type=Boolean, dest='svg')
        self.arg_parser.add_argument('--format-threadlist', type=Boolean, dest='threadlist')
        self.arg_parser.add_argument('--x-repeats', type=int, dest='x_repeats', default=1)
        self.arg_parser.add_argument('--y-repeats', type=int, dest='y_repeats', default=1)
        self.arg_parser.add_argument('--x-spacing', type=float, dest='x_spacing', default=100)
        self.arg_parser.add_argument('--y-spacing', type=float, dest='y_spacing', default=100)
        self.formats.append('svg')
        self.formats.append('threadlist')

    def effect(self):
        if not self.get_elements():
            return

        self.metadata = self.get_inkstitch_metadata()
        collapse_len = self.metadata['collapse_len_mm']
        min_stitch_len = self.metadata['min_stitch_len_mm']
        patches = self.elements_to_stitch_groups(self.elements)
        stitch_plan = stitch_groups_to_stitch_plan(patches, collapse_len=collapse_len, min_stitch_len=min_stitch_len)

        if self.options.x_repeats != 1 or self.options.y_repeats != 1:
            dx = self.options.x_spacing * PIXELS_PER_MM
            dy = self.options.y_spacing * PIXELS_PER_MM
            offsets = []
            for x in range(self.options.x_repeats):
                for y in range(self.options.y_repeats):
                    offsets.append(Point(x * dx, y * dy))
            stitch_plan = stitch_plan.make_offsets(offsets)

        base_file_name = self.get_base_file_name()
        path = tempfile.mkdtemp()

        files = []

        for format in self.formats:
            if getattr(self.options, format):
                output_file = os.path.join(path, "%s.%s" % (base_file_name, format))
                if format == 'svg':
                    document = deepcopy(self.document.getroot())
                    with open(output_file, 'w', encoding='utf-8') as svg:
                        svg.write(etree.tostring(document).decode('utf-8'))
                elif format == 'threadlist':
                    output_file = os.path.join(path, "%s_%s.txt" % (base_file_name, _("threadlist")))
                    output = open(output_file, 'w', encoding='utf-8')
                    output.write(self.get_threadlist(stitch_plan, base_file_name))
                    output.close()
                else:
                    write_embroidery_file(output_file, stitch_plan, self.document.getroot())
                files.append(output_file)

        if not files:
            self.errormsg(_("No embroidery file formats selected."))

        temp_file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)

        # in windows, failure to close here will keep the file locked
        temp_file.close()

        with ZipFile(temp_file.name, "w") as zip_file:
            for file in files:
                zip_file.write(file, os.path.basename(file))

        # inkscape will read the file contents from stdout and copy
        # to the destination file that the user chose
        with open(temp_file.name, 'rb') as output_file:
            sys.stdout.buffer.write(output_file.read())

        os.remove(temp_file.name)
        for file in files:
            os.remove(file)
        os.rmdir(path)

        # don't let inkex output the SVG!
        sys.exit(0)

    def get_threadlist(self, stitch_plan, design_name):
        ThreadCatalog().match_and_apply_palette(stitch_plan, self.get_inkstitch_metadata()['thread-palette'])
        thread_used = []

        thread_output = "%s\n" % _("Design Details")
        thread_output += "==============\n\n"

        thread_output += "%s: %s\n" % (_("Title"), design_name)
        thread_output += "%s (mm): %.2f x %.2f\n" % (_("Size"),  stitch_plan.dimensions_mm[0], stitch_plan.dimensions_mm[1])
        thread_output += "%s: %s\n" % (_("Stitches"), stitch_plan.num_stitches)
        thread_output += "%s: %s\n\n" % (_("Colors"), stitch_plan.num_colors)

        thread_output += "%s\n" % _("Thread Order")
        thread_output += "============\n\n"

        for i, color_block in enumerate(stitch_plan):
            thread = color_block.color

            thread_output += str(i + 1) + " "
            string = "%s #%s - %s (#%s)" % (thread.name, thread.number, thread.manufacturer, thread.hex_digits.lower())
            thread_output += string + "\n"

            thread_used.append(string)

        thread_output += "\n"
        thread_output += _("Thread Used") + "\n"
        thread_output += "============" + "\n\n"

        for thread in set(thread_used):
            thread_output += thread + "\n"

        return "%s" % thread_output
