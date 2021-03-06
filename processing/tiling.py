#!/usr/bin/env python
#
## Copyright (c) 2013
##
## Joachim Ungar (ju@eox.at)
##
## Permission is hereby granted, free of charge, to any person obtaining a copy 
## of this software and associated documentation files (the "Software"), to deal 
## in the Software without restriction, including without limitation the rights 
## to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
## copies of the Software, and to permit persons to whom the Software is furnished
##  to do so, subject to the following conditions:
##
## The above copyright notice and this permission notice shall be included in all 
## copies or substantial portions of the Software.
##
## THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
## IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
## FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
## AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER 
## LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
## OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE 
## SOFTWARE.

import sys
import argparse
import os
import tempfile
import subprocess
import numpy
import osgeo.gdal as gdal
import osgeo.gdalconst as gdalconst
from osgeo.gdalconst import *
import osr
import plugins
import pkgutil
from multiprocessing import Pool
from itertools import product


# Configuration
# =============

SOURCE_X=0
SOURCE_Y=0
# number of digits in tile naming (e.g. X001Y001)
DIGITS=3

loaded_plugins = {}


def main(args):

    parser = argparse.ArgumentParser()
    parser.add_argument("source_vrt", nargs=1, type=str)
    parser.add_argument("tile_xsize", nargs=1, type=int)
    parser.add_argument("tile_ysize", nargs=1, type=int)
    parser.add_argument("margin", nargs=1, type=int)
    parser.add_argument("dest", nargs=1, type=str)
    parser.add_argument("multi", nargs=1, type=int)
    parser.add_argument("--create_vrt", action="store_true")
    parser.add_argument("--naming_srtm", action="store_true")
    parser.add_argument("--resume", action="store_true")

    subparsers = parser.add_subparsers(help='sub-command help')

    for loader, module_name, ispkg in pkgutil.iter_modules(plugins.__path__):
        plugin = loader.find_module(module_name).load_module(module_name)

        subparser = subparsers.add_parser(module_name)
        plugin.config_subparser(subparser)
        subparser.set_defaults(method=module_name)
        loaded_plugins[module_name] = plugin

    parsed = parser.parse_args(args)

    #print parsed.method

    source_vrt = parsed.source_vrt[0]
    source = str(source_vrt)
    tile_xsize = parsed.tile_xsize[0]
    tile_ysize = parsed.tile_ysize[0]
    margin = parsed.margin[0]
    dest = parsed.dest[0]
    multi = parsed.multi[0]

    #print parsed.create_vrt
    
    ds = gdal.Open(source, GA_ReadOnly)

    # determine VRT pixel size
    vrt_xsize = ds.RasterXSize
    vrt_ysize = ds.RasterYSize
    print vrt_xsize, vrt_ysize

    # determine tile numbers
    tile_count_x = int(numpy.ceil(float(vrt_xsize)/float(tile_xsize)))
    tile_count_y = int(numpy.ceil(float(vrt_ysize)/float(tile_ysize)))
    print tile_count_x, tile_count_y

    if (parsed.method == "rescale"):

        xresolution = float(parsed.x)
        yresolution = float(parsed.y)

        xscale = xresolution/tile_xsize
        yscale = yresolution/tile_ysize
    
        vrt_xsize = int(int(vrt_xsize*xscale)/xscale)
        vrt_ysize = int(int(vrt_ysize*yscale)/yscale)
        
        #print vrt_xsize, vrt_ysize

    tiles = list(product(xrange(tile_count_x), xrange(tile_count_y)))


    from functools import partial
    f = partial(worker,
        parsed=parsed, 
        tile_count_x=tile_count_x, 
        tile_count_y=tile_count_y,
        margin=margin,
        vrt_xsize=vrt_xsize,
        vrt_ysize=vrt_ysize,
        source=source,
        dest=dest,
        source_vrt=source_vrt
    )


    pool = Pool(multi)
    errors = pool.map(f, tiles)

    #for error in errors:
    #    print "%s: %s \n" %(error[0], error[1])

    # create VRT
    if parsed.create_vrt:
        target_vrt = dest.rsplit("/")[0] + ".vrt"
        target_tiffs = dest + "*.tif"
        create_vrt = "gdalbuildvrt -overwrite %s %s" %(target_vrt, target_tiffs)
        print create_vrt
        os.system(create_vrt)

def worker((i, j), parsed, tile_count_x, tile_count_y, margin, vrt_xsize, vrt_ysize, source, dest, source_vrt):
    try:
        temp_metatile = "/tmp/tmp_metatile_%s.tif" % os.getpid() #= tempfile.mktemp()#= "temp_metatile.tif"
        temp_processed = "/tmp/tmp_processed_%s.tif" % os.getpid()#= tempfile.mktemp() #"temp_processed.tif"

        with open(temp_metatile, "w+"):
            pass
        with open(temp_processed, "w+"):
            pass

        tile_xsize = parsed.tile_xsize[0]
        tile_ysize = parsed.tile_ysize[0]

        # determine tile boundaries
        tile_offsetx = SOURCE_X + i*tile_xsize
        tile_offsety = SOURCE_Y + j*tile_ysize

        # reduce tile size if end of column/row                
        if i==tile_count_x-1 and (vrt_xsize-((i*tile_xsize))!=0):
            tile_xsize = vrt_xsize-i*tile_xsize            
        if j==tile_count_y-1 and (vrt_ysize-((j*tile_ysize))!=0):
            tile_ysize = vrt_ysize-j*tile_ysize

        #calculate metatile boundaries
        metatile_offsetx = tile_offsetx - margin
        metatile_xsize = tile_xsize + 2 * margin

        metatile_offsety = tile_offsety - margin
        metatile_ysize = tile_ysize + 2 * margin

        #TODO crop to tile boundaries & save
        save_offsetx = margin
        save_offsety = margin
        save_xsize = tile_xsize
        save_ysize = tile_ysize
            
        # clip metatile if outside of input file's boundaries
        # if negative, set save_offset to 0 and make metatile-margin
        # if out of max, make metatile-margin
        if (metatile_offsetx<0):
            metatile_offsetx=0
            save_offsetx=0
            metatile_xsize=metatile_xsize-margin

        if (metatile_offsety<0):
            metatile_offsety=0
            save_offsety=0
            metatile_ysize=metatile_ysize-margin

        if (metatile_offsetx+metatile_xsize > vrt_xsize):
            metatile_xsize = metatile_xsize - margin

        if (metatile_offsety+metatile_ysize > vrt_ysize):
            metatile_ysize = metatile_ysize - margin

        ds = gdal.Open(source)
        band = ds.GetRasterBand(1)
        nodata = int(band.GetNoDataValue() or 0)
        data = numpy.array(band.ReadAsArray(tile_offsetx, tile_offsety, tile_xsize, tile_ysize))


        # define output tile name
        target = dest+"X"+str(i).zfill(DIGITS)+"Y"+str(j).zfill(DIGITS)+".tif"

        ot = ""

        if parsed.naming_srtm:
            geotransform = ds.GetGeoTransform(1)
            xpixelsize = geotransform[1]
            ypixelsize = geotransform[5]
            xorigin = geotransform[0]
            yorigin = geotransform[3]
            lon_character = "E"
            lat_character = "N"

            lon_number = int(round(xorigin + xpixelsize*tile_offsetx))
            if lon_number<0:
                lon_number=-lon_number
                lon_character = "W"

            lat_number = int(round(yorigin + ypixelsize*(tile_offsety+tile_ysize)))
            if lat_number<0:
                lat_number=-lat_number
                lat_character = "S"

            target = dest+lat_character+str(lat_number).zfill(2)+lon_character+str(lon_number).zfill(3)+".tif"

        tile_exists = False
        if parsed.resume:
            #check whether target tile exists
            tile_exists = os.path.isfile(target)
        
        #print "\n"
        #print "processing tile " + target

        # skip if tile is empty
        data[data==0]=nodata
        if numpy.all(data==nodata):
            #print "source data empty, skipping"
            message = "source data empty"
            pass
        elif (tile_exists==True):
            #print "tile exists, skipping"
            message = "tile exists" 
            pass
        else:           
            if not os.path.exists(dest):
                os.makedirs(dest) 
            open(target, 'a').close()     

            save_metatile = "gdal_translate %s -of GTiff %s -srcwin %s %s %s %s > /dev/null" %(source_vrt, temp_metatile, metatile_offsetx, metatile_offsety, metatile_xsize, metatile_ysize)
            os.system(save_metatile)
            
            loaded_plugins[parsed.method].process(parsed, target, temp_metatile, temp_processed, save_offsetx, save_offsety, save_xsize, save_ysize, nodata, ot, metatile_xsize, metatile_ysize)

            #print "tile processed\n"
            message = "successfully processed"

    except Exception, e:
        print "%s: %s " %(target, e)
        return target, e
    else:
        pass
    finally:
        # clean up
        os.remove(temp_metatile)
        os.remove(temp_processed)
    print "%s: %s \n" %(target, message)
    return target, "ok"
    

    

if __name__ == "__main__":
        main(sys.argv[1:])
