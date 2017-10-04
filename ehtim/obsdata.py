from __future__ import division
from __future__ import print_function
from builtins import str
from builtins import range
from builtins import object

import string, copy
import numpy as np
import numpy.lib.recfunctions as rec
import matplotlib.pyplot as plt
import scipy.optimize as opt
import itertools as it
import sys

import ehtim.image
import ehtim.observing.obs_simulate
import ehtim.io.save
import ehtim.io.load

from ehtim.const_def import *
from ehtim.observing.obs_helpers import *

##################################################################################################
# Obsdata object
##################################################################################################

class Obsdata(object):
    """A polarimetric VLBI observation of visibility amplitudes and phases (in Jy).

       Attributes:
           source (str): The source name
           ra (float): The source Right Ascension in fractional hours
           dec (float): The source declination in fractional degrees
           mjd (int): The integer MJD of the observation
           tstart (float): The start time of the observation in hours
           tstop (float): The end time of the observation in hours
           rf (float): The observation frequency in Hz
           bw (float): The observation bandwidth in Hz

           ampcal (bool): True if amplitudes calibrated
           phasecal (bool): True if phases calibrated
           opacitycal (bool): True if time-dependent opacities correctly accounted for in sigmas
           frcal (bool): True if feed rotation calibrated out of visibilities
           dcal (bool): True if D terms calibrated out of visibilities
           timetype (str): How to interpret tstart and tstop; either 'GMST' or 'UTC'

           tarr (numpy.recarray): The array of telescope data with datatype DTARR
           tkey (dict): A dictionary of rows in the tarr for each site name
           data (numpy.recarray): the basic data with datatype DTPOL
    """

    def __init__(self, ra, dec, rf, bw, datatable, tarr, source=SOURCE_DEFAULT, mjd=MJD_DEFAULT, ampcal=True, phasecal=True, opacitycal=True, dcal=True, frcal=True, timetype='UTC'):
        """A polarimetric VLBI observation of visibility amplitudes and phases (in Jy).

           Args:
               ra (float): The source Right Ascension in fractional hours
               dec (float): The source declination in fractional degrees
               rf (float): The observation frequency in Hz
               bw (float): The observation bandwidth in Hz
               datatable (numpy.recarray): the basic data with datatype DTPOL
               tarr (numpy.recarray): The array of telescope data with datatype DTARR
               source (str): The source name
               mjd (int): The integer MJD of the observation
               ampcal (bool): True if amplitudes calibrated
               phasecal (bool): True if phases calibrated
               opacitycal (bool): True if time-dependent opacities correctly accounted for in sigmas
               frcal (bool): True if feed rotation calibrated out of visibilities
               dcal (bool): True if D terms calibrated out of visibilities
               timetype (str): How to interpret tstart and tstop; either 'GMST' or 'UTC'


           Returns:
               obsdata (Obsdata): an Obsdata object
        """

        if len(datatable) == 0:
            raise Exception("No data in input table!")
        if (datatable.dtype != DTPOL):
            raise Exception("Data table should be a recarray with datatable.dtype = %s" % DTPOL)

        # Set the various parameters
        self.source = str(source)
        self.ra = float(ra)
        self.dec = float(dec)
        self.rf = float(rf)
        self.bw = float(bw)
        self.ampcal = bool(ampcal)
        self.phasecal = bool(phasecal)
        self.opacitycal = bool(opacitycal)
        self.dcal = bool(dcal)
        self.frcal = bool(frcal)

        if timetype not in ['GMST', 'UTC']:
            raise Exception("timetype must by 'GMST' or 'UTC'")
        self.timetype = timetype
        self.tarr = tarr

        # Dictionary of array indices for site names
        self.tkey = {self.tarr[i]['site']: i for i in range(len(self.tarr))}

        # Time partition the datatable
        datalist = []
        for key, group in it.groupby(datatable, lambda x: x['time']):
            datalist.append(np.array([obs for obs in group]))

        # Remove conjugate baselines
        obsdata = []
        for tlist in datalist:
            blpairs = []
            for dat in tlist:
                if not (set((dat['t1'], dat['t2']))) in blpairs:

                     # Reverse the baseline in the right order for uvfits:
                     if(self.tkey[dat['t1']] < self.tkey[dat['t2']]):
                        (dat['t1'], dat['t2']) = (dat['t2'], dat['t1'])
                        dat['u'] = -dat['u']
                        dat['v'] = -dat['v']
                        dat['vis'] = np.conj(dat['vis'])
                        dat['uvis'] = np.conj(dat['uvis'])
                        dat['qvis'] = np.conj(dat['qvis'])
                        dat['vvis'] = np.conj(dat['vvis'])

                     # Append the data point
                     blpairs.append(set((dat['t1'],dat['t2'])))
                     obsdata.append(dat)

        obsdata = np.array(obsdata, dtype=DTPOL)

        # Sort the data by time
        obsdata = obsdata[np.argsort(obsdata, order=['time','t1'])]

        # Save the data
        self.data = obsdata

        # Get tstart, mjd and tstop
        times = self.unpack(['time'])['time']
        self.tstart = times[0]
        self.mjd = int(mjd)
        #self.mjd = fracmjd(mjd, self.tstart)
        self.tstop = times[-1]
        if self.tstop < self.tstart:
            self.tstop += 24.0

    def copy(self):
        """Copy the observation object.

           Args:

           Returns:
               (Obsdata): a copy of the Obsdata object.
        """
        newobs = Obsdata(self.ra, self.dec, self.rf, self.bw, self.data, self.tarr, source=self.source, mjd=self.mjd,
                         ampcal=self.ampcal, phasecal=self.phasecal, opacitycal=self.opacitycal, dcal=self.dcal, frcal=self.frcal)
        return newobs

    def data_conj(self):
        """Make a data array including all conjugate baselines. 

           Args:

           Returns:
                (numpy.recarray): a copy of the Obsdata.data table (type DTPOL) including all conjugate baselines.
        """

        data = np.empty(2*len(self.data), dtype=DTPOL)

        # Add the conjugate baseline data
        for f in DTPOL:
            f = f[0]
            if f in ["t1", "t2", "tau1", "tau2"]:
                if f[-1]=='1': f2 = f[:-1]+'2'
                else: f2 = f[:-1]+'1'
                data[f] = np.hstack((self.data[f], self.data[f2]))
            elif f in ["u","v"]:
                data[f] = np.hstack((self.data[f], -self.data[f]))
            elif f in ["vis","qvis","uvis","vvis"]:
                data[f] = np.hstack((self.data[f], np.conj(self.data[f])))
            else:
                data[f] = np.hstack((self.data[f], self.data[f]))

        # Sort the data by time
        data = data[np.argsort(data['time'])]
        return data

    def tlist(self, conj=False):
        """Group the data in a list of equal time observation datatables.

           Args:
                conj (bool): True if tlist_out includes conjugate baselines.
           Returns:
                (list): a list of data tables (type DTPOL) containing time-partitioned data
        """

        if conj:
            data = self.data_conj()
        else:
            data = self.data

        # Use itertools groupby function to partition the data
        datalist = []
        for key, group in it.groupby(data, lambda x: x['time']):
            datalist.append(np.array([obs for obs in group]))

        return np.array(datalist)

    def bllist(self,conj=False):
        """Group the data in a list of same baseline datatables.

           Args:
                conj (bool): True if tlist_out includes conjugate baselines.
           Returns:
                (list): a list of data tables (type DTPOL) containing baseline-partitioned data
        """
        data = self.data
        idx = np.lexsort((data['t2'], data['t1']))
        
        datalist = []
        for key, group in it.groupby(data[idx], lambda x: set((x['t1'], x['t2'])) ):

            datalist.append(np.array([obs for obs in group]))

        return np.array(datalist)
       
    def unpack_bl(self, site1, site2, fields, ang_unit='deg', debias=False, timetype=False):
        """Unpack the data over time on the selected baseline site1-site2.

           Args:
                site1 (str): First site name
                site2 (str): Second site name
                fields (list): list of unpacked quantities from available quantities in FIELDS
                ang_unit (str): 'deg' for degrees and 'rad' for radian phases
                debias (bool): True to debias visibility amplitudes
                timetype (str): 'GMST' or 'UTC' 
           Returns:
                (numpy.recarray): unpacked numpy array with data in fields requested
        """

        if timetype==False:
            timetype=self.timetype
            
        # If we only specify one field
        if timetype not  in ['GMST','UTC','utc','gmst']:
            raise Exception("timetype should be 'GMST' or 'UTC'!")
        allfields = ['time']

        if not isinstance(fields, list): allfields.append(fields)
        else:
            for i in range(len(fields)): allfields.append(fields[i])

        # Get field data on selected baseline
        allout = []

        # Get the data from data table on the selected baseline
        tlist = self.tlist(conj=True)
        for scan in tlist:
            for obs in scan:
                if (obs['t1'].decode(), obs['t2'].decode()) == (site1, site2):
                    obs = np.array([obs])
                    out = self.unpack_dat(obs, allfields, ang_unit=ang_unit, debias=debias)

                    #ANDREW TODO DOES THIS WORK
                    if timetype in ['UTC','utc'] and self.timetype=='GMST':
                        out['time'] = gmst_to_utc(out['time'])
                    elif timetype in ['GMST','gmst'] and self.timetype=='UTC':
                        out['time'] = utc_to_gmst(out['time'])

                    allout.append(out)


        return np.array(allout)

    def unpack(self, fields, mode='all', ang_unit='deg',  debias=False, conj=False):
        """Unpack the data for the whole observation .

           Args:
                fields (list): list of unpacked quantities from availalbe quantities in FIELDS
                mode (str): 'all' returns all data in single table, 'time' groups output by equal time, 'bl' groups by baseline
                ang_unit (str): 'deg' for degrees and 'rad' for radian phases
                debias (bool): True to debias visibility amplitudes
                conj (bool): True to include conjugate baselines
           Returns:
                (numpy.recarray): unpacked numpy array with data in fields requested

        """

        
        if not mode in ('time', 'all', 'bl'):
            raise Exception("possible options for mode are 'time', 'all' and 'bl'")
                    
        # If we only specify one field
        if not isinstance(fields, list): fields = [fields]
        
        if mode=='all':    
            if conj:
                data = self.data_conj()     
            else:
                data = self.data
            allout=self.unpack_dat(data, fields, ang_unit=ang_unit, debias=debias)

        elif mode=='time':
            allout=[]
            tlist = self.tlist(conj=True)
            for scan in tlist:
                out=self.unpack_dat(scan, fields, ang_unit=ang_unit, debias=debias)
                allout.append(out)

        elif mode=='bl':
            allout = []
            bllist = self.bllist()
            for bl in bllist:
                out = self.unpack_dat(bl, fields, ang_unit=ang_unit, debias=debias)
                allout.append(out)
        
        return np.array(allout)

        
    def unpack_dat(self, data, fields, conj=False, ang_unit='deg', debias=False):
        """Unpack the data in a data recarray.

           Args:
                data (numpy.recarray): data recarray of format DTPOL
                fields (list): list of unpacked quantities from availalbe quantities in FIELDS
                ang_unit (str): 'deg' for degrees and 'rad' for radian phases
                debias (bool): True to debias visibility amplitudes
                conj (bool): True to include conjugate baselines
           Returns:
                (numpy.recarray): unpacked numpy array with data in fields requested

        """

        if ang_unit=='deg': angle=DEGREE
        else: angle = 1.0

        # If we only specify one field
        if type(fields) == str: 
            fields = [fields]

        # Get field data
        allout = []
        for field in fields:
            if field in ["time","time_utc","time_gmst"]:
                out = data['time']
                ty='f8'
            elif field in ["u","v","tint","tau1","tau2"]:
                out = data[field]
                ty = 'f8'
            elif field in ["uvdist"]:
                out = np.abs(data['u'] + 1j * data['v'])
                ty = 'f8'
            elif field in ["t1","el1","par_ang1","hr_ang1"]:
                sites = data["t1"]
                keys = [self.tkey[site] for site in sites]
                tdata = self.tarr[keys]
                out = sites
                ty = 'a32'
            elif field in ["t2","el2","par_ang2","hr_ang2"]:
                sites = data["t2"]
                keys = [self.tkey[site] for site in sites]
                tdata = self.tarr[keys]
                out = sites
                ty = 'a32'
            elif field in ["vis","amp","phase","snr","sigma","sigma_phase"]:
                out = data['vis']
                sig = data['sigma']
                ty = 'c16'
            elif field in ["qvis","qamp","qphase","qsnr","qsigma","qsigma_phase"]:
                out = data['qvis']
                sig = data['qsigma']
                ty = 'c16'
            elif field in ["uvis","uamp","uphase","usnr","usigma","usigma_phase"]:
                out = data['uvis']
                sig = data['usigma']
                ty = 'c16'
            elif field in ["vvis","vamp","vphase","vsnr","vsigma","vsigma_phase"]:
                out = data['vvis']
                sig = data['vsigma']
                ty = 'c16'
            elif field in ["pvis","pamp","pphase","psnr","psigma","psigma_phase"]:
                out = data['qvis'] + 1j * data['uvis']
                sig = np.sqrt(data['qsigma']**2 + data['usigma']**2)
                ty = 'c16'
            elif field in ["m","mamp","mphase","msnr","msigma","msigma_phase"]:
                out = (data['qvis'] + 1j * data['uvis'])/data['vis']
                sig = merr(data['sigma'], data['qsigma'], data['usigma'], data['vis'], out)
                ty = 'c16'
            elif field in ["rrvis", "rramp", "rrphase", "rrsnr", "rrsigma", "rrsigma_phase"]:
                out = data['vis'] + data['vvis']
                sig = np.sqrt(data['sigma']**2 + data['vsigma']**2)
                ty = 'c16'
            elif field in ["llvis", "llamp", "llphase", "llsnr", "llsigma", "llsigma_phase"]:
                out = data['vis'] - data['vvis']
                sig = np.sqrt(data['sigma']**2 + data['vsigma']**2)
                ty = 'c16'
            elif field in ["rlvis", "rlamp", "rlphase", "rlsnr", "rlsigma", "rlsigma_phase"]:
                out = data['qvis'] + 1j*data['uvis']
                sig = np.sqrt(data['qsigma']**2 + data['usigma']**2)
                ty = 'c16'
            elif field in ["lrvis", "lramp", "lrphase", "lrsnr", "lrsigma", "lrsigma_phase"]:
                out = data['qvis'] - 1j*data['uvis']
                sig = np.sqrt(data['qsigma']**2 + data['usigma']**2)
                ty = 'c16'

            else: raise Exception("%s is not valid field \n" % field +
                                  "valid field values are: " + ' '.join(FIELDS))

            if field in ["time_utc"] and self.timetype=='GMST':
                out = gmst_to_utc(out, self.mjd)
            if field in ["time_gmst"] and self.timetype=='UTC':
                out = utc_to_gmst(out, self.mjd)


            # Elevation and Parallactic Angles
            if field in ["el1","el2","hr_ang1","hr_ang2","par_ang1","par_ang2"]:
                if self.timetype=='GMST':
                    times_sid = data['time']
                else:
                    times_sid = utc_to_gmst(data['time'], self.mjd)

                thetas = np.mod((times_sid - self.ra)*HOUR, 2*np.pi)
                coords = tdata[['x','y','z']].view(('f8', 3))
                el_angle = elev(earthrot(coords, thetas), self.sourcevec())
                latlon = xyz_2_latlong(coords)
                hr_angles = hr_angle(times_sid*HOUR, latlon[:,1], self.ra*HOUR)

                if field in ["el1","el2"]:
                    out = el_angle/angle
                    ty  = 'f8'
                if field in ["hr_ang1","hr_ang2"]:
                    out = hr_angles/angle
                    ty  = 'f8'
                if field in ["par_ang1","par_ang2"]:
                    par_ang = par_angle(hr_angles, latlon[:,0], self.dec*DEGREE)
                    out = par_ang/angle
                    ty  = 'f8'

            # Get arg/amps/snr
            if field in ["amp", "qamp", "uamp","vamp","pamp","mamp","rramp","llamp","rlamp","lramp"]:
                out = np.abs(out)

                if debias:
                    #print("Debiasing amplitudes in unpack!")
                    out = amp_debias(out, sig)

                ty = 'f8'
            elif field in ["phase", "qphase", "uphase", "vphase","pphase", "mphase","rrphase","llphase","lrphase","rlphase"]:
                out = np.angle(out)/angle
                ty = 'f8'
            elif field in ["sigma","qsigma","usigma","vsigma","psigma","msigma","rrsigma","llsigma","rlsigma","lrsigma"]:
                out = np.abs(sig)
                ty = 'f8'
            elif field in ["sigma_phase","qsigma_phase","usigma_phase","vsigma_phase","psigma_phase","msigma_phase",
                           "rrsigma_phase","llsigma_phase","rlsigma_phase","lrsigma_phase"]:
                out = np.abs(sig)/np.abs(out)/angle
                ty = 'f8'
            elif field in ["snr", "qsnr", "usnr", "vsnr", "psnr", "msnr","rrsnr","llsnr","rlsnr","lrsnr"]:
                out = np.abs(out)/np.abs(sig)
                ty = 'f8'

            # Reshape and stack with other fields
            out = np.array(out, dtype=[(field, ty)])

            if len(allout) > 0: 
                allout = rec.merge_arrays((allout, out), asrecarray=True, flatten=True)
            else:
                allout = out

        return allout

    def sourcevec(self):
        """Return the source position vector in geocentric coordinates at 0h GMST.

           Args:

           Returns:
                (numpy.array): normal vector pointing to source in geocentric coordinates (m)
        """
        return np.array([np.cos(self.dec*DEGREE), 0, np.sin(self.dec*DEGREE)])

    def res(self):
        """Return the nominal resolution (1/longest baseline) of the observation in radians.

           Args:

           Returns:
                (float): normal array resolution in radians
        """
        return 1.0/np.max(self.unpack('uvdist')['uvdist'])

               

    def split_obs(self):
        """Split single observation into multiple observation files, one per scan.
           
           Args:

           Returns: 
                (list): list of single-scan Obsdata objects
        """

        print("Splitting Observation File into " + str(len(self.tlist())) + " scans")

        # ote that the tarr of the output includes all sites, even those that don't participate in the scan
        splitlist = [Obsdata(self.ra, self.dec, self.rf, self.bw, tdata, self.tarr, source=self.source,
                             mjd=self.mjd, ampcal=self.ampcal, phasecal=self.phasecal)
                     for tdata in self.tlist()
                    ]

        return splitlist

    def avg_coherent(self, inttime):
        """Coherently average data along u,v tracs in chunks of length inttime (sec).

           Args:
                inttime (float): coherent integration time in seconds
           Returns:
                (Obsdata): Obsdata object containing averaged data
        """
    
        alldata_list = ['vis', 'u', 'v', 
                        'sigma', 't1', 't2', 'tau1', 'tau2',  
                        'uvis', 'qvis', 'vvis', 'qsigma', 
                        'usigma', 'vsigma', 'tint', 'time']

        timesplit = self.unpack(alldata_list, mode='time')

        inttime_hr = inttime/3600.
        datatable = []
        timeregion =  []
        time_current = timesplit[0]['time'][0]
        tavg = 1

        for t in range(0, len(timesplit)):
            sys.stdout.write('\rAveraging Scans %i/%i in %f sec ints : Reduced Data %i/%i' % (t,len(timesplit),inttime, tavg,t))
            sys.stdout.flush()
            
            # accumulate data in a time region
            if (timesplit[t]['time'][0] - time_current < inttime_hr):
                
                for i in range(0,len(timesplit[t]['time'])):
                    timeregion.append(np.array
                             ((
                               timesplit[t]['time'][i], timesplit[t]['tint'][i], 
                               timesplit[t]['t1'][i], timesplit[t]['t2'][i], timesplit[t]['tau1'][i], timesplit[t]['tau2'][i], 
                               timesplit[t]['u'][i], timesplit[t]['v'][i],
                               timesplit[t]['vis'][i], timesplit[t]['qvis'][i], timesplit[t]['uvis'][i], timesplit[t]['vvis'][i],
                               timesplit[t]['sigma'][i], timesplit[t]['qsigma'][i], timesplit[t]['usigma'][i], timesplit[t]['vsigma'][i]
                               ), dtype=DTPOL
                             ))

            # average data in a time region
            else:
                tavg += 1
                obs_timeregion = Obsdata(self.ra, self.dec, self.rf, self.bw, np.array(timeregion), self.tarr, source=self.source, mjd=self.mjd)
                            
                blsplit = obs_timeregion.unpack(alldata_list, mode='bl')
                for bl in range(0,len(blsplit)):
                    
                    bldata = blsplit[bl]
                    datatable.append(np.array
                             ((
                               np.mean(obs_timeregion.data['time']), np.mean(bldata['tint']), 
                               bldata['t1'][0], bldata['t2'][0], np.mean(bldata['tau1']), np.mean(bldata['tau2']), 
                               np.mean(bldata['u']), np.mean(bldata['v']),
                               np.mean(bldata['vis']), np.mean(bldata['qvis']), np.mean(bldata['uvis']), np.mean(bldata['vvis']),
                               np.sqrt(np.sum(bldata['sigma']**2)/len(bldata)**2), np.sqrt(np.sum(bldata['qsigma']**2)/len(bldata)**2), 
                               np.sqrt(np.sum(bldata['usigma']**2)/len(bldata)**2), np.sqrt(np.sum(bldata['vsigma']**2)/len(bldata)**2)
                               ), dtype=DTPOL
                             ))


                # start a new time region            
                timeregion = []
                time_current = timesplit[t]['time'][0]
                for i in range(0, len(timesplit[t]['time'])):
                    timeregion.append(np.array
                             ((
                               timesplit[t]['time'][i], timesplit[t]['tint'][i], 
                               timesplit[t]['t1'][i], timesplit[t]['t2'][i], timesplit[t]['tau1'][i], timesplit[t]['tau2'][i], 
                               timesplit[t]['u'][i], timesplit[t]['v'][i],
                               timesplit[t]['vis'][i], timesplit[t]['qvis'][i], timesplit[t]['uvis'][i], timesplit[t]['vvis'][i],
                               timesplit[t]['sigma'][i], timesplit[t]['qsigma'][i], timesplit[t]['usigma'][i], timesplit[t]['vsigma'][i]
                               ), dtype=DTPOL
                             ))
        print(len(datatable))
            
        return Obsdata(self.ra, self.dec, self.rf, self.bw, np.array(datatable), self.tarr, source=self.source, mjd=self.mjd)
      
    def dirtybeam(self, npix, fov, pulse=PULSE_DEFAULT):
        """Make an image of the observation dirty beam.

           Args:
               npix (int): The pixel size of the square output image.
               fov (float): The field of view of the square output image in radians.
               pulse (function): The function convolved with the pixel values for continuous image.

           Returns:
               (Image): an Image object with the dirty beam.
        """

        pdim = fov/npix
        u = self.unpack('u')['u']
        v = self.unpack('v')['v']

        xlist = np.arange(0,-npix,-1)*pdim + (pdim*npix)/2.0 - pdim/2.0

        im = np.array([[np.mean(np.cos(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])

        im = im[0:npix, 0:npix]

        # Normalize to a total beam power of 1
        im = im/np.sum(im)

        src = self.source + "_DB"
        return ehtim.image.Image(im, pdim, self.ra, self.dec, rf=self.rf, source=src, mjd=self.mjd, pulse=pulse)

    def cleanbeam(self, npix, fov, pulse=PULSE_DEFAULT):
        """Make an image of the observation clean beam.

           Args:
               npix (int): The pixel size of the square output image.
               fov (float): The field of view of the square output image in radians.
               pulse (function): The function convolved with the pixel values for continuous image.

           Returns:
               (Image): an Image object with the clean beam.
        """

        im = ehtim.image.make_square(self, npix, fov, pulse=pulse)
        beamparams = self.fit_beam()
        im = im.add_gauss(1.0, beamparams)
        return im

    def fit_beam(self):
        """Fit a gaussian to the dirty beam and return the parameters (fwhm_maj, fwhm_min, theta).

           Returns:
               (tuple): a tuple (fwhm_maj, fwhm_min, theta) of the dirty beam parameters in radians.
        """

        # Define the sum of squares function that compares the quadratic expansion of the dirty image
        # with the quadratic expansion of an elliptical gaussian
        def fit_chisq(beamparams, db_coeff):

            (fwhm_maj2, fwhm_min2, theta) = beamparams
            a = 4 * np.log(2) * (np.cos(theta)**2/fwhm_min2 + np.sin(theta)**2/fwhm_maj2)
            b = 4 * np.log(2) * (np.cos(theta)**2/fwhm_maj2 + np.sin(theta)**2/fwhm_min2)
            c = 8 * np.log(2) * np.cos(theta) * np.sin(theta) * (1.0/fwhm_maj2 - 1.0/fwhm_min2)
            gauss_coeff = np.array((a,b,c))

            chisq = np.sum((np.array(db_coeff) - gauss_coeff)**2)

            return chisq

        # These are the coefficients (a,b,c) of a quadratic expansion of the dirty beam
        # For a point (x,y) in the image plane, the dirty beam expansion is 1-ax^2-by^2-cxy
        u = self.unpack('u')['u']
        v = self.unpack('v')['v']
        n = float(len(u))
        abc = (2.*np.pi**2/n) * np.array([np.sum(u**2), np.sum(v**2), 2*np.sum(u*v)])
        abc = 1e-20 * abc # Decrease size of coefficients

        # Fit the beam
        guess = [(50)**2, (50)**2, 0.0]
        params = opt.minimize(fit_chisq, guess, args=(abc,), method='Powell')

        # Return parameters, adjusting fwhm_maj and fwhm_min if necessary
        if params.x[0] > params.x[1]:
            fwhm_maj = 1e-10*np.sqrt(params.x[0])
            fwhm_min = 1e-10*np.sqrt(params.x[1])
            theta = np.mod(params.x[2], np.pi)
        else:
            fwhm_maj = 1e-10*np.sqrt(params.x[1])
            fwhm_min = 1e-10*np.sqrt(params.x[0])
            theta = np.mod(params.x[2] + np.pi/2.0, np.pi)

        return np.array((fwhm_maj, fwhm_min, theta))

    def dirtyimage(self, npix, fov, pulse=PULSE_DEFAULT):
        """Make the observation dirty image (direct Fourier transform).

           Args:
               npix (int): The pixel size of the square output image.
               fov (float): The field of view of the square output image in radians.
               pulse (function): The function convolved with the pixel values for continuous image.

           Returns:
               (Image): an Image object with dirty image.
        """

        pdim = fov/npix
        u = self.unpack('u')['u']
        v = self.unpack('v')['v']
        vis = self.unpack('vis')['vis']
        qvis = self.unpack('qvis')['qvis']
        uvis = self.unpack('uvis')['uvis']
        vvis = self.unpack('vvis')['vvis']

        xlist = np.arange(0,-npix,-1)*pdim + (pdim*npix)/2.0 - pdim/2.0

        # Take the DFTS
        # Shouldn't need to real about conjugate baselines b/c unpack does not return them
        im  = np.array([[np.mean(np.real(vis)*np.cos(2*np.pi*(i*u + j*v)) -
                                 np.imag(vis)*np.sin(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])
        qim = np.array([[np.mean(np.real(qvis)*np.cos(2*np.pi*(i*u + j*v)) -
                                 np.imag(qvis)*np.sin(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])
        uim = np.array([[np.mean(np.real(uvis)*np.cos(2*np.pi*(i*u + j*v)) -
                                 np.imag(uvis)*np.sin(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])
        vim = np.array([[np.mean(np.real(vvis)*np.cos(2*np.pi*(i*u + j*v)) -
                                 np.imag(vvis)*np.sin(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])

        dim = np.array([[np.mean(np.cos(2*np.pi*(i*u + j*v)))
                  for i in xlist]
                  for j in xlist])

        # Final normalization
        im  = im /np.sum(dim)
        qim = qim/np.sum(dim)
        uim = uim/np.sum(dim)
        vim = vim/np.sum(dim)

        im = im[0:npix, 0:npix]
        qim = qim[0:npix, 0:npix]
        uim = uim[0:npix, 0:npix]
        vim = vim[0:npix, 0:npix]

        out = ehtim.image.Image(im, pdim, self.ra, self.dec, rf=self.rf, source=self.source, mjd=self.mjd, pulse=pulse)
        out.add_qu(qim, uim)
        out.add_v(vim)

        return out

    def deblur(self):
        """Deblur the observation obs by dividing by the Sgr A* redscattering kernel.

           Args:
 
           Returns:
               (Obsdata): a new deblurred observation object.
        """

        # make a copy of observation data
        datatable = (self.copy()).data

        vis = datatable['vis']
        qvis = datatable['qvis']
        uvis = datatable['uvis']
        vvis = datatable['vvis']
        sigma = datatable['sigma']
        qsigma = datatable['qsigma']
        usigma = datatable['usigma']
        vsigma = datatable['vsigma']
        u = datatable['u']
        v = datatable['v']

        # divide visibilities by the scattering kernel
        for i in range(len(vis)):
            ker = sgra_kernel_uv(self.rf, u[i], v[i])
            vis[i] = vis[i]/ker
            qvis[i] = qvis[i]/ker
            uvis[i] = uvis[i]/ker
            vvis[i] = vvis[i]/ker
            sigma[i] = sigma[i]/ker
            qsigma[i] = qsigma[i]/ker
            usigma[i] = usigma[i]/ker
            vsigma[i] = vsigma[i]/ker

        datatable['vis'] = vis
        datatable['qvis'] = qvis
        datatable['uvis'] = uvis
        datatable['vvis'] = vvis
        datatable['sigma'] = sigma
        datatable['qsigma'] = qsigma
        datatable['usigma'] = usigma
        datatable['vsigma'] = vsigma

        obsdeblur = Obsdata(self.ra, self.dec, self.rf, self.bw, datatable, self.tarr, source=self.source, mjd=self.mjd,
                            ampcal=self.ampcal, phasecal=self.phasecal, opacitycal=self.opacitycal, dcal=self.dcal, frcal=self.frcal)
        return obsdeblur

    def fit_gauss(self, flux=1.0, fittype='amp', paramguess=(100*RADPERUAS, 100*RADPERUAS, 0.)):
        """Fit a gaussian to either Stokes I complex visibilities or Stokes I visibility amplitudes.

           Args:
                flux (float): total flux in the fitted gaussian
                fitttype (str): "amp" to fit to visibilty amplitudes
                paramguess (tuble): initial guess of fit Gaussian (fwhm_maj, fwhm_min, theta) 
           Returns:
                (tuple) : a tuple (fwhm_maj, fwhm_min, theta) of the fit Gaussian parameters in radians.
        """

        vis = self.data['vis']
        u = self.data['u']
        v = self.data['v']
        sig = self.data['sigma']

        # error function
        if fittype=='amp':
            def errfunc(p):
            	vismodel = gauss_uv(u,v, flux, p, x=0., y=0.)
            	err = np.sum((np.abs(vis)-np.abs(vismodel))**2/sig**2)
            	return err
        else:
            def errfunc(p):
            	vismodel = gauss_uv(u,v, flux, p, x=0., y=0.)
            	err = np.sum(np.abs(vis-vismodel)**2/sig**2)
            	return err

        optdict = {'maxiter':5000} # minimizer params
        res = opt.minimize(errfunc, paramguess, method='Powell',options=optdict)
        return res.x

    def bispectra(self, vtype='vis', mode='time', count='min',timetype=False):
        """Return a recarray of the equal time bispectra.

           Args:
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble bispectra
               mode (str): If 'time', return phases in a list of equal time arrays, if 'all', return all phases in a single array
               count (str): If 'min', return minimal set of phases, if 'max' return all closure phases up to reordering
               timetype (str): 'GMST' or 'UTC'
           Returns:
               (numpy.recarry): A recarray of the bispectra values with datatype DTBIS

        """
        if timetype==False:
            timetype=self.timetype
        if not mode in ('time', 'all'):
            raise Exception("possible options for mode are 'time' and 'all'")
        if not count in ('min', 'max'):
            raise Exception("possible options for count are 'min' and 'max'")
        if not vtype in ('vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'):
            raise Exception("possible options for vtype are 'vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'")
        if timetype not  in ['GMST','UTC','gmst','utc']:
            raise Exception("timetype should be 'GMST' or 'UTC'!")



        # Generate the time-sorted data with conjugate baselines
        tlist = self.tlist(conj=True)
        outlist = []
        bis = []
        tt = 1
        for tdata in tlist:
            sys.stdout.flush()
            sys.stdout.write('\rGetting bispectra: type: %s count: %s scan %i/%i ' % (vtype, count, tt, len(tlist)))

            tt += 1

            time = tdata[0]['time']
            if timetype in ['GMST','gmst'] and self.timetype=='UTC':
                time = utc_to_gmst(time, self.mjd)
            if timetype in ['UTC','utc'] and self.timetype=='GMST':
                time = gmst_to_utc(time, self.mjd) 
            sites = list(set(np.hstack((tdata['t1'],tdata['t2']))))

            # Create a dictionary of baselines at the current time incl. conjugates;
            l_dict = {}
            for dat in tdata:
                l_dict[(dat['t1'], dat['t2'])] = dat

            # Determine the triangles in the time step

            # Minimal Set
            if count == 'min':
                # If we want a minimal set, choose triangles with the minimum sefd reference
                # Unless there is no sefd data, in which case choose the northernmost
                # TODO This should probably be an sefdr + sefdl average instead
                if len(set(self.tarr['sefdr'])) > 1:
                    ref = sites[np.argmin([self.tarr[self.tkey[site]]['sefdr'] for site in sites])]
                else:
                    ref = sites[np.argmax([self.tarr[self.tkey[site]]['z'] for site in sites])]
                sites.remove(ref)

                # Find all triangles that contain the ref
                tris = list(it.combinations(sites,2))
                tris = [(ref, t[0], t[1]) for t in tris]

            # Maximal  Set - find all triangles
            elif count == 'max':
                tris = list(it.combinations(sites,3))

            # Generate bispectra for each triangle
            for tri in tris:
                # The ordering is north-south
                a1 = np.argmax([self.tarr[self.tkey[site]]['z'] for site in tri])
                a3 = np.argmin([self.tarr[self.tkey[site]]['z'] for site in tri])
                a2 = 3 - a1 - a3
                tri = (tri[a1], tri[a2], tri[a3])

                # Select triangle entries in the data dictionary
                try:
                    l1 = l_dict[(tri[0], tri[1])]
                    l2 = l_dict[(tri[1],tri[2])]
                    l3 = l_dict[(tri[2], tri[0])]
                except KeyError:
                    continue

                (bi, bisig) = make_bispectrum(l1,l2,l3,vtype)

                # Append to the equal-time list
                bis.append(np.array((time, tri[0], tri[1], tri[2],
                                     l1['u'], l1['v'], l2['u'], l2['v'], l3['u'], l3['v'],
                                     bi, bisig), dtype=DTBIS))

            # Append to outlist
            if mode=='time' and len(bis) > 0:
                outlist.append(np.array(bis))
                bis = []

            elif mode=='all':
                outlist = np.array(bis)

        return np.array(outlist)

    def c_phases(self, vtype='vis', mode='time', count='min', ang_unit='deg', timetype=False):
        """Return a recarray of the equal time closure phases.

           Args:
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure phases
               mode (str): If 'time', return phases in a list of equal time arrays, if 'all', return all phases in a single array
               count (str): If 'min', return minimal set of phases, if 'max' return all closure phases up to reordering
               ang_unit (str): If 'deg', return closure phases in degrees, else return in radians
               timetype (str): 'UTC' or 'GMST'

           Returns:
               (numpy.recarry): A recarray of the closure phases with datatype DTPHASE
        """
        if timetype==False:
            timetype=self.timetype
        if not mode in ('time', 'all'):
            raise Exception("possible options for mode are 'time' and 'all'")
        if not count in ('max', 'min'):
            raise Exception("possible options for count are 'max' and 'min'")
        if not vtype in ('vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'):
            raise Exception("possible options for vtype are 'vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'")
        if timetype not  in ['GMST','UTC','gmst','utc']:
            raise Exception("timetype should be 'GMST' or 'UTC'!")


        if ang_unit=='deg': angle=DEGREE
        else: angle = 1.0

        # Get the bispectra data
        bispecs = self.bispectra(vtype=vtype, mode='time', count=count, timetype=timetype)

        # Reformat into a closure phase list/array
        outlist = []
        cps = []
        sys.stdout.write('\rReformatting bispectra to closure phase...')
        for bis in bispecs:
            for bi in bis:
                if len(bi) == 0: continue
                bi.dtype.names = ('time','t1','t2','t3','u1','v1','u2','v2','u3','v3','cphase','sigmacp')
                bi['sigmacp'] = np.real(bi['sigmacp']/np.abs(bi['cphase'])/angle)
                bi['cphase'] = np.real((np.angle(bi['cphase'])/angle))
                cps.append(bi.astype(np.dtype(DTCPHASE)))
            if mode == 'time' and len(cps) > 0:
                outlist.append(np.array(cps))
                cps = []

        if mode == 'all':
            outlist = np.array(cps)
        return np.array(outlist)

    def bispectra_tri(self, site1, site2, site3, vtype='vis',timetype=False):
        """Return complex bispectrum  over time on a triangle (1-2-3).

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               site3 (str): station 3 name
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure phases
               timetype (str): 'UTC' or 'GMST'

           Returns:
               (numpy.recarry): A recarray of the closure phases on this triangle with datatype DTPHASE
        """
        if timetype==False:
            timetype=self.timetype
        # Get closure phases (maximal set)
        bs = self.bispectra(mode='time', count='max', vtype=vtype, timetype=timetype)

        # Get requested closure phases over time
        tri = (site1, site2, site3)
        outdata = []
        for entry in bs:
            for obs in entry:
                obstri = (obs['t1'],obs['t2'],obs['t3'])
                if set(obstri) == set(tri):
                    # Flip the sign of the closure phase if necessary
                    parity = paritycompare(tri, obstri)

                    if parity==-1:
                        obs['bispec'] = np.abs(obs['bispec'])*np.exp(-1j*np.angle(obs['bispec']))
                        t2 = copy.deepcopy(obs['t2'])
                        u2 = copy.deepcopy(obs['u2'])
                        v2 = copy.deepcopy(obs['v2'])

                        obs['t2'] = obs['t3']
                        obs['u2'] = obs['u3']
                        obs['v2'] = obs['v3']

                        obs['t3'] = t2
                        obs['u3'] = u2
                        obs['v3'] = v2

                    outdata.append(np.array(obs, dtype=DTBIS))
                    continue
        return np.array(outdata)


    def cphase_tri(self, site1, site2, site3, vtype='vis', ang_unit='deg', timetype=False):
        """Return closure phase  over time on a triangle (1-2-3).

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               site3 (str): station 3 name
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure phases
               ang_unit (str): If 'deg', return closure phases in degrees, else return in radians
               timetype (str): 'GMST' or 'UTC'

           Returns:
               (numpy.recarry): A recarray of the closure phases on this triangle with datatype DTPHASE
        """
        if timetype==False:
            timetype=self.timetype 
        # Get closure phases (maximal set)
        cphases = self.c_phases(mode='time', count='max', vtype=vtype, ang_unit=ang_unit,timetype=timetype)

        # Get requested closure phases over time
        tri = (site1, site2, site3)
        outdata = []
        for entry in cphases:
            for obs in entry:
                obstri = (obs['t1'],obs['t2'],obs['t3'])
                if set(obstri) == set(tri):
                    # Flip the sign of the closure phase if necessary
                    parity = paritycompare(tri, obstri)

                    obs['cphase'] *= parity

                    if parity==-1:
                        t2 = copy.deepcopy(obs['t2'])
                        u2 = copy.deepcopy(obs['u2'])
                        v2 = copy.deepcopy(obs['v2'])

                        obs['t2'] = obs['t3']
                        obs['u2'] = obs['u3']
                        obs['v2'] = obs['v3']

                        obs['t3'] = t2
                        obs['u3'] = u2
                        obs['v3'] = v2

                    outdata.append(np.array(obs, dtype=DTCPHASE))
                    continue
        return np.array(outdata)

    def c_amplitudes(self, vtype='vis', mode='time', count='min', ctype='camp', debias=True,timetype=False):
        """Return a recarray of the equal time closure amplitudes.

           Args:
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure amplitudes
               ctype (str): The closure amplitude type ('camp' or 'logcamp')
               mode (str): If 'time', return amplitudes in a list of equal time arrays, if 'all', return all amplitudes in a single array
               count (str): If 'min', return minimal set of amplitudes, if 'max' return all closure amplitudes up to inverses
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               timetype (str): 'GMST' or 'UTC'

           Returns:
               (numpy.recarry): A recarray of the closure amplitudes with datatype DTCAMP

        """
        if timetype==False:
            timetype=self.timetype
        if not mode in ('time','all'):
            raise Exception("possible options for mode are 'time' and 'all'")
        if not count in ('max', 'min'):
            raise Exception("possible options for count are 'max' and 'min'")
        if not vtype in ('vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'):
            raise Exception("possible options for vtype are 'vis', 'qvis', 'uvis','vvis','rrvis','lrvis','rlvis','llvis'")
        if not (ctype in ['camp', 'logcamp']):
            raise Exception("closure amplitude type must be 'camp' or 'logcamp'!")
        if timetype not  in ['GMST','UTC','gmst','utc']:
            raise Exception("timetype should be 'GMST' or 'UTC'!")

        # Get data sorted by time
        tlist = self.tlist(conj=True)
        outlist = []
        cas = []
        tt = 1
        for tdata in tlist:
            sys.stdout.flush()
            sys.stdout.write('\rGetting closure amps: type: %s %s count: %s scan %i/%i ' % (vtype, ctype, count, tt, len(tlist)))
            tt += 1

            time = tdata[0]['time']
            if timetype in ['GMST','gmst'] and self.timetype=='UTC':
                time = utc_to_gmst(time, self.mjd)
            if timetype in ['UTC','utc'] and self.timetype=='GMST':
                time = gmst_to_utc(time, self.mjd) 

            sites = np.array(list(set(np.hstack((tdata['t1'],tdata['t2'])))))
            if len(sites) < 4:
                continue

            # Create a dictionary of baseline data at the current time including conjugates;
            l_dict = {}
            for dat in tdata:
                l_dict[(dat['t1'], dat['t2'])] = dat

            # Minimal set
            if count == 'min':
                # If we want a minimal set, choose the minimum sefd reference
                # TODO this should probably be an sefdr + sefdl average instead
                sites = sites[np.argsort([self.tarr[self.tkey[site]]['sefdr'] for site in sites])]
                ref = sites[0]

                # Loop over other sites >=3 and form minimal closure amplitude set
                for i in range(3, len(sites)):
                    if (ref, sites[i]) not in l_dict.keys():
                        continue

                    blue1 = l_dict[ref, sites[i]] # MJ: This causes a KeyError in some cases, probably with flagged data or something
                    for j in range(1, i):
                        if j == i-1: k = 1
                        else: k = j+1

                        if (sites[i], sites[j]) not in l_dict.keys(): # MJ: I tried joining these into a single if statement using or without success... no idea why...
                            continue

                        if (ref, sites[k]) not in l_dict.keys():
                            continue

                        if (sites[j], sites[k]) not in l_dict.keys():
                            continue

                        #ANDREW TODO behavior when no baseline?
                        try:
                            red1 = l_dict[sites[i], sites[j]]
                            red2 = l_dict[ref, sites[k]]
                            blue2 = l_dict[sites[j], sites[k]]
                        except KeyError:
                            continue
                            
                        # Compute the closure amplitude and the error
                        (camp, camperr) = make_closure_amplitude(red1, red2, blue1, blue2, vtype, ctype=ctype)

                        # Add the closure amplitudes to the equal-time list
                        # Our site convention is (12)(34)/(14)(23)
                        cas.append(np.array((time,
                                             ref, sites[i], sites[j], sites[k],
                                             blue1['u'], blue1['v'], blue2['u'], blue2['v'],
                                             red1['u'], red1['v'], red2['u'], red2['v'],
                                             camp, camperr),
                                             dtype=DTCAMP))

            # Maximal Set
            elif count == 'max':
                # Find all quadrangles
                quadsets = list(it.combinations(sites,4))
                for q in quadsets:
                    # Loop over 3 closure amplitudes
                    # Our site convention is (12)(34)/(14)(23)
                    for quad in (q, [q[0],q[2],q[1],q[3]], [q[0],q[1],q[3],q[2]]):

                        # Blue is numerator, red is denominator
                        #ANDREW TODO behavior when no baseline?
                        try:
                            blue1 = l_dict[quad[0], quad[1]] 
                            blue2 = l_dict[quad[2], quad[3]]
                            red1 = l_dict[quad[0], quad[3]]
                            red2 = l_dict[quad[1], quad[2]]
                        except KeyError:
                            continue

                        # Compute the closure amplitude and the error
                        (camp, camperr) = make_closure_amplitude(red1, red2, blue1, blue2, vtype, ctype=ctype)

                        # Add the closure amplitudes to the equal-time list
                        # Our site convention is (12)(34)/(14)(23)
                        cas.append(np.array((time,
                                             quad[0], quad[1], quad[2], quad[3],
                                             blue1['u'], blue1['v'], blue2['u'], blue2['v'],
                                             red1['u'], red1['v'], red2['u'], red2['v'],
                                             camp, camperr),
                                             dtype=DTCAMP))

            # Append all equal time closure amps to outlist
            if mode=='time':
                outlist.append(np.array(cas))
                cas = []

            elif mode=='all':
                outlist = np.array(cas)

        return np.array(outlist)

    def camp_quad(self, site1, site2, site3, site4, vtype='vis', ctype='camp', debias=True, timetype=False):
        """Return closure phase over time on a quadrange (1-2)(3-4)/(1-4)(2-3).

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               site3 (str): station 3 name
               site4 (str): station 4 name
               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure amplitudes
               ctype (str): The closure amplitude type ('camp' or 'logcamp')
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               timetype (str): 'UTC' or 'GMST'

           Returns:
               (numpy.recarry): A recarray of the closure amplitudes with datatype DTCAMP

        """

        if timetype==False:
            timetype=self.timetype
        
        quad = (site1, site2, site3, site4)
        r1 = set((site1, site2))
        r2 = set((site3, site4))

        b1 = set((site1, site4))
        b2 = set((site2, site3))


        # Get the closure amplitudes
        outdata = []
        camps = self.c_amplitudes(mode='time', count='max', vtype='vis', ctype=ctype, debias=debias,timetype=timetype)
        for entry in camps:
            for obs in entry:
                obsquad = (obs['t1'],obs['t2'],obs['t3'],obs['t4'])

                if set(quad) == set(obsquad):
                    num = [set((obs['t1'], obs['t2'])), set((obs['t3'], obs['t4']))]
                    denom = [set((obs['t1'], obs['t4'])), set((obs['t2'], obs['t3']))]

                    # flip inverse closure amplitudes
                    if (r1 in denom) and (r2 in denom) and (b1 in num) and (b2 in num):

                        t2 = copy.deepcopy(obs['t2'])
                        u2 = copy.deepcopy(obs['u2'])
                        v2 = copy.deepcopy(obs['v2'])

                        t3 = copy.deepcopy(obs['t3'])
                        u3 = copy.deepcopy(obs['u3'])
                        v3 = copy.deepcopy(obs['v3'])

                        obs['t2'] = obs['t4']
                        obs['u2'] = obs['u4']
                        obs['v2'] = obs['v4']

                        obs['t3'] = t2
                        obs['u3'] = u2
                        obs['v3'] = v2

                        obs['t4'] = t3
                        obs['u4'] = u3
                        obs['v4'] = v3

                        if ctype=='logcamp':
                            obs['camp'] = -obs['camp']
                        else:
                            obs['camp'] = 1./obs['camp']
                            obs['sigmaca'] = obs['sigmaca']*(obs['camp']**2)
                        outdata.append(np.array(obs, dtype=DTCAMP))
                    elif (r1 in num) and (r2 in num) and (b1 in denom) and (b2 in denom):
                        outdata.append(np.array(obs, dtype=DTCAMP))
                    continue


        return np.array(outdata)


    def plotall(self, field1, field2, ebar=True, rangex=False, rangey=False, conj=False, show=True, axis=False, color='b', ang_unit='deg', debias=True):
        """Make a scatter plot of 2 real baseline observation fields in (FIELDS) with error bars.

           Args:
               field1 (str): x-axis field (from FIELDS)
               field2 (str): y-axis field (from FIELDS)

               rangex (list): [xmin, xmax] x-axis limits
               rangey (list): [ymin, ymax] y-axis limits

               ebar (bool): Plot error bars if True
               conj (bool): Plot conjuage baseline data points if True
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               show (bool): Display the plot if true
               axis (matplotlib.axes.Axes): add plot to this axis
               color (str): Color of scatterplot points
               ang_unit (str): phase unit 'deg' or 'rad' 


           Returns:
               (matplotlib.axes.Axes): Axes object with data plot

        """




        # Determine if fields are valid
        if (field1 not in FIELDS) and (field2 not in FIELDS):
            raise Exception("valid fields are " + ' '.join(FIELDS))

        # Unpack x and y axis data
        data = self.unpack([field1, field2], conj=conj, ang_unit=ang_unit, debias=debias)

        # X error bars
        if sigtype(field1):
            sigx = self.unpack(sigtype(field2), conj=conj, ang_unit=ang_unit)[sigtype(field1)]
        else:
            sigx = None

        # Y error bars
        if sigtype(field2):
            sigy = self.unpack(sigtype(field2), conj=conj, ang_unit=ang_unit)[sigtype(field2)]
        else:
            sigy = None

        # Data ranges
        if not rangex:
            rangex = [np.min(data[field1]) - 0.2 * np.abs(np.min(data[field1])),
                      np.max(data[field1]) + 0.2 * np.abs(np.max(data[field1]))]
        if not rangey:
            rangey = [np.min(data[field2]) - 0.2 * np.abs(np.min(data[field2])),
                      np.max(data[field2]) + 0.2 * np.abs(np.max(data[field2]))]

        # Plot the data
        if axis:
            x = axis
        else:
            fig=plt.figure()
            x = fig.add_subplot(1,1,1)

        if ebar and (np.any(sigy) or np.any(sigx)):
            x.errorbar(data[field1], data[field2], xerr=sigx, yerr=sigy, fmt='.', color=color)
        else:
            x.plot(data[field1], data[field2], '.', color=color)

        x.set_xlim(rangex)
        x.set_ylim(rangey)
        x.set_xlabel(field1)
        x.set_ylabel(field2)

        if show:
            plt.show(block=False)
        return x

    def plot_bl(self, site1, site2, field, ebar=True, rangex=False, rangey=False, show=True, axis=False, color='b', ang_unit='deg', debias=True, timetype=False):
        """Plot a field over time on a baseline site1-site2.

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               field (str): y-axis field (from FIELDS)

               rangex (list): [xmin, xmax] x-axis (time) limits
               rangey (list): [ymin, ymax] y-axis limits

               ebar (bool): Plot error bars if True
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               show (bool): Display the plot if true
               axis (matplotlib.axes.Axes): add plot to this axis
               color (str): Color of scatterplot points
               ang_unit (str): phase unit 'deg' or 'rad' 

           Returns:
               (matplotlib.axes.Axes): Axes object with data plot

        """
        if timetype==False:
            timetype=self.timetype
        if ang_unit=='deg': angle=DEGREE
        else: angle = 1.0

        # Determine if fields are valid
        if field not in FIELDS:
            raise Exception("valid fields are " + string.join(FIELDS))

        plotdata = self.unpack_bl(site1, site2, field, ang_unit=ang_unit, debias=debias, timetype=timetype)
        if not rangex:
            rangex = [self.tstart,self.tstop]
        if not rangey:
            rangey = [np.min(plotdata[field]) - 0.2 * np.abs(np.min(plotdata[field])),
                      np.max(plotdata[field]) + 0.2 * np.abs(np.max(plotdata[field]))]

        # Plot the data
        if axis:
            x = axis
        else:
            fig = plt.figure()
            x = fig.add_subplot(1,1,1)
        
        if ebar and sigtype(field)!=False:
            errdata = self.unpack_bl(site1, site2, sigtype(field), ang_unit=ang_unit, debias=debias)
            x.errorbar(plotdata['time'][:,0], plotdata[field][:,0], yerr=errdata[sigtype(field)][:,0], fmt='.', color=color)
        else:
            x.plot(plotdata['time'][:,0], plotdata[field][:,0],'.', color=color)

        x.set_xlim(rangex)
        x.set_ylim(rangey)
        x.set_xlabel(self.timetype + ' (hr)')
        x.set_ylabel(field)
        x.set_title('%s - %s'%(site1,site2))

        if show:
            plt.show(block=False)

        return x

    def plot_cphase(self, site1, site2, site3, vtype='vis', ebar=True, rangex=False, rangey=False, show=True, axis=False, color='b', ang_unit='deg', timetype=False):
        """Plot closure phase over time on a triangle (1-2-3).

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               site3 (str): station 3 name

               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble bispectra
               ang_unit (str): phase unit 'deg' or 'rad' 
               timetype (str): 'GMST' or 'UTC'
               rangex (list): [xmin, xmax] x-axis (time) limits
               rangey (list): [ymin, ymax] y-axis (phase) limits

               ebar (bool): Plot error bars if True
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               show (bool): Display the plot if true
               axis (matplotlib.axes.Axes): add plot to this axis
               color (str): Color of scatterplot points
               


           Returns:
               (matplotlib.axes.Axes): Axes object with data plot

        """
        if timetype==False:
            timetype=self.timetype
        if ang_unit=='deg': angle=1.0
        else: angle = eh.DEGREE

        # Get closure phases (maximal set)
        cpdata = self.cphase_tri(site1, site2, site3, vtype=vtype, timetype=timetype)
        plotdata = np.array([[obs['time'],obs['cphase']*angle,obs['sigmacp']] for obs in cpdata])

        if len(plotdata) == 0:
            print("No closure phases on this triangle!")
            return

        # Data ranges
        if not rangex:
            rangex = [self.tstart,self.tstop]
        if not rangey:
            rangey = [np.min(plotdata[:,1]) - 0.2 * np.abs(np.min(plotdata[:,1])),
                      np.max(plotdata[:,1]) + 0.2 * np.abs(np.max(plotdata[:,1]))]

        # Plot the data
        if axis:
            x = axis
        else:
            fig=plt.figure()
            x = fig.add_subplot(1,1,1)

        if ebar and np.any(plotdata[:,2]):
            x.errorbar(plotdata[:,0], plotdata[:,1], yerr=plotdata[:,2], fmt='.', color=color)
        else:
            x.plot(plotdata[:,0], plotdata[:,1], '.', color=color)

        x.set_xlim(rangex)
        x.set_ylim(rangey)
        x.set_xlabel(self.timetype + ' (h)')
        x.set_ylabel('Closure Phase (deg)')
        x.set_title('%s - %s - %s' % (site1,site2,site3))
        if show:
            plt.show(block=False)
        return x

    def plot_camp(self, site1, site2, site3, site4, vtype='vis', ctype='camp', debias=True,timetype=False,
                        ebar=True, rangex=False, rangey=False, show=True, axis=False, color='b'):
        """Plot closure amplitude over time on a quadrange (1-2)(3-4)/(1-4)(2-3).

           Args:
               site1 (str): station 1 name
               site2 (str): station 2 name
               site3 (str): station 3 name
               site4 (str): station 4 name

               vtype (str): The visibilty type ('vis','qvis','uvis','vvis','pvis') from which to assemble closure amplitudes
               ctype (str): The closure amplitude type ('camp' or 'logcamp')
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               timetype (str): 'GMST' or 'UTC'

               rangex (list): [xmin, xmax] x-axis (time) limits
               rangey (list): [ymin, ymax] y-axis (phase) limits

               ebar (bool): Plot error bars if True
               debias (bool): If True, debias the closure amplitude - the individual visibility amplitudes are always debiased.
               show (bool): Display the plot if true
               axis (matplotlib.axes.Axes): add plot to this axis
               color (str): Color of scatterplot points


           Returns:
               (matplotlib.axes.Axes): Axes object with data plot

        """
        if timetype==False:
            timetype=self.timetype
        # Get closure phases (maximal set)
        cpdata = self.camp_quad(site1, site2, site3, site4, vtype=vtype, ctype=ctype, debias=debias, timetype=timetype)
        plotdata = np.array([[obs['time'],obs['camp'],obs['sigmaca']] for obs in cpdata])
        plotdata = np.array(plotdata)
        
        if len(plotdata) == 0:
            print("No closure amplitudes on this quadrangle!")
            return

        # Data ranges
        if not rangex:
            rangex = [self.tstart,self.tstop]
        if not rangey:
            rangey = [np.min(plotdata[:,1]) - 0.2 * np.abs(np.min(plotdata[:,1])),
                      np.max(plotdata[:,1]) + 0.2 * np.abs(np.max(plotdata[:,1]))]

        # Plot the data
        if axis:
            x = axis
        else:
            fig=plt.figure()
            x = fig.add_subplot(1,1,1)

        if ebar and np.any(plotdata[:,2]):
            x.errorbar(plotdata[:,0], plotdata[:,1], yerr=plotdata[:,2], fmt='.', color=color)
        else:
            x.plot(plotdata[:,0], plotdata[:,1],'.', color=color)

        x.set_xlim(rangex)
        x.set_ylim(rangey)
        x.set_xlabel(self.timetype + ' (h)')
        if ctype=='camp':
            x.set_ylabel('Closure Amplitude')
        elif ctype=='logcamp':
            x.set_ylabel('Log Closure Amplitude')
        x.set_title('(%s - %s)(%s - %s)/(%s - %s)(%s - %s)'%(site1,site2,site3,site4,
                                                           site1,site4,site2,site3))
        if show:
            plt.show(block=False)
            return
        else:
            return x

    def save_txt(self, fname):
        """Save visibility data to a text file.

           Args:
                fname (str): path to output text file
        """

        ehtim.io.save.save_obs_txt(self,fname)
        return

    def save_uvfits(self, fname):
        """Save visibility data to uvfits file.

           Args:
                fname (str): path to output text file
        """

        ehtim.io.save.save_obs_uvfits(self,fname)
        return

    def save_oifits(self, fname, flux=1.0):
        """ Save visibility data to oifits. Polarization data is NOT saved.

            Args:
                fname (str): path to output text file
                flux (float): normalization total flux
        """
        #Antenna diameter currently incorrect and the exact times are not correct in the datetime object
        #Please contact Katie Bouman (klbouman@mit.edu) for any questions on this function

        ehtim.io.save.save_obs_oifits(self, fname, flux=flux)
        return

    # TODO -- this could be redundant with cphase_tri
    # would need to  change how it's implemented in closure.py
    def get_cphase_curves(self, tris,timetype=False):
        """Get closure phase cuves over time on all requested triangles

           Args:
                tris (list): list of station triangles
                timetype (str): 'UTC' or 'GMST'
           Returns:
                (list) : list of closure phase recarrays over time
        """
        if timetype==False:
            timetype=self.timetype
        # Get closure phases (maximal set)
        cphases = self.c_phases(mode='time', count='max',timetype=timetype)

        # Get requested closure phases over time
        cps = list()
        for tri in tris:
            cpdata = []
            for entry in cphases:
                for obs in entry:
                    obstri = (obs['t1'],obs['t2'],obs['t3'])
                    if set(obstri) == set(tri):
                        # Flip the sign of the closure phase if necessary
                        parity = paritycompare(tri, obstri)
                        cpdata.append([obs['time'], parity*obs['cphase'], obs['sigmacp']])
                        continue

            cpdata = np.array(cpdata)

            if len(cpdata) == 0:
                #print "No closure phases on " + '%s - %s - %s' % (tri[0],tri[1],tri[2])
                cps.append(None)
            else:
                cps.append(np.array([cpdata[:,0], cpdata[:,1], cpdata[:,2]]))

        return cps

    # TODO -- this could be redundant with cphase_tri
    # would need to  change how it's implemented in closure.py
    def get_camp_curves(self, quads, timetype=False):
        """Get closure amplitude over time on all requested quadrangeles
           (1-2)(3-4)/(1-4)(2-3)

           Args:
                quads (list): list of station quadrangles
                timetype (str): 'UTC' or 'GMST'
           Returns:
                (list) : list of closure amplitude recarrays over time
        """
        if timetype==False:
            timetype=self.timetype

        # Get the closure amplitudes
        camps = self.c_amplitudes(mode='time', count='max',timetype=timetype)

        cas = list()
        for quad in quads:
            b1 = set((quad[0], quad[1]))
            r1 = set((quad[0], quad[3]))

            cadata = []
            for entry in camps:
                for obs in entry:
                    obsquad = (obs['t1'],obs['t2'],obs['t3'],obs['t4'])
                    if set(quad) == set(obsquad):
                        num = [set((obs['t1'], obs['t2'])), set((obs['t3'], obs['t4']))]
                        denom = [set((obs['t1'], obs['t4'])), set((obs['t2'], obs['t3']))]

                        if (b1 in num) and (r1 in denom):
                            cadata.append([obs['time'], obs['camp'], obs['sigmaca']])
                        elif (r1 in num) and (b1 in denom):
                            cadata.append([obs['time'], 1./obs['camp'], obs['sigmaca']/(obs['camp']**2)])
                        continue

            cadata = np.array(cadata)
            if len(cadata) == 0:
                #print "No closure amplitudes on this quadrangle!"
                cas.append(None)
            else:
                cas.append(np.array([cadata[:,0], cadata[:,1], cadata[:,2]]))

        return cas

##################################################################################################
# Observation creation functions
##################################################################################################

def merge_obs(obs_List):
    """Merge a list of observations into a single observation file.

       Args:
           obs_List (list): list of split observation Obsdata objects.
       Returns:
           mergeobs (Obsdata): merged Obsdata object containing all scans in input list
    """

    if (len(set([obs.ra for obs in obs_List])) > 1 or
        len(set([obs.dec for obs in obs_List])) > 1 or
        len(set([obs.rf for obs in obs_List])) > 1 or
        len(set([obs.bw for obs in obs_List])) > 1 or
        len(set([obs.source for obs in obs_List])) > 1 or
        len(set([np.floor(obs.mjd) for obs in obs_List])) > 1):

        raise Exception("All observations must have the same parameters!")
        return

    #The important things to merge are the mjd, the data, and the list of telescopes
    data_merge = np.hstack([obs.data for obs in obs_List])

    mergeobs = Obsdata(obs_List[0].ra, obs_List[0].dec, obs_List[0].rf, obs_List[0].bw, data_merge, np.unique(np.concatenate([obs.tarr for obs in obs_List])),
                       source=obs_List[0].source, mjd=obs_List[0].mjd, ampcal=obs_List[0].ampcal, phasecal=obs_List[0].phasecal)

    return mergeobs

def load_txt(fname):
    """Read an observation from a text file.

       Args:
           fname (str): path to input text file
       Returns:
           obs (Obsdata): Obsdata object loaded from file
    """
    return ehtim.io.load.load_obs_txt(fname)

def load_uvfits(fname, flipbl=False, force_singlepol=None):
    """Load observation data from a uvfits file.

       Args:
           fname (str): path to input text file
           flipbl (bool): flip baseline phases if True.
           force_singlepol (str): 'R' or 'L' to load only 1 polarization
       Returns:
           obs (Obsdata): Obsdata object loaded from file
    """
    return ehtim.io.load.load_obs_uvfits(fname, flipbl=flipbl, force_singlepol=force_singlepol)

def load_oifits(fname, flux=1.0):
    """Load data from an oifits file. Does NOT currently support polarization.

       Args:
           fname (str): path to input text file
           flux (float): normalization total flux
       Returns:
           obs (Obsdata): Obsdata object loaded from file
    """
    return ehtim.io.load.load_obs_oifits(fname, flux=flux)

def load_maps(arrfile, obsspec, ifile, qfile=0, ufile=0, vfile=0, src=SOURCE_DEFAULT, mjd=MJD_DEFAULT, ampcal=False, phasecal=False):
    """Read an observation from a maps text file and return an Obsdata object.

       Args:
           arrfile (str): path to input array file
           obsspec (str): path to input obs spec file
           ifile (str): path to input Stokes I data file
           qfile (str): path to input Stokes Q data file
           ufile (str): path to input Stokes U data file
           vfile (str): path to input Stokes V data file
           src (str): source name
           mjd (int): integer observation  MJD
           ampcal (bool): True if amplitude calibrated
           phasecal (bool): True if phase calibrated
       Returns:
           obs (Obsdata): Obsdata object loaded from file
    """
    return ehtim.io.load.load_obs_maps(arrfile, obsspec, ifile, qfile=qfile, ufile=ufile, vfile=vfile, src=src, mjd=mjd, ampcal=ampcal, phasecal=phasecal)