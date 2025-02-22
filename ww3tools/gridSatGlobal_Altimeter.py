#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
gridSatGlobal_Altimeter.py

VERSION AND LAST UPDATE:
 v1.0  04/04/2022
 v1.1  07/18/2022

PURPOSE:
 Script to take altimeter tracks and collocate into regular
  lat/lon grid (gridInfo.nc, generated by preprGridMask.py)
  and hourly time interval (for different time intervals, edit atime array)
 A total of 14 satellite missions are listed below. The period of each
  altimeter can be verified at:
  https://www.sciencedirect.com/science/article/pii/S0273117721000594
  https://ars.els-cdn.com/content/image/1-s2.0-S0273117721000594-gr1_lrg.jpg

USAGE:
 This program processes one satellite mission per run, entered as 
  argument (only the ID, sys.argv), see the sdname for the list of 
  altimeters available.
 Altimeters must have been previously downloaded (see wfetchsatellite_AODN_Altimeter.sh)
 Path where altimeter data is saved must be informed and 
  edited (see dirs below)
 Check the pre-selected parameters below for the altimeter collocation 
  and date interval (datemin and datemax)
 Example (from linux terminal command line):
  An example for JASON3 (first in the sdname list) is
   nohup python3 gridSatGlobal_Altimeter.py 0 >> nohup_sat0.out 2>&1 &

OUTPUT:
 netcdf file AltimeterGridded_*.nc containing the collocated altimeter
  data into lat/lon grid points given by gridInfo.nc
 hsk: significant wave height, Ku or Ka altimeter band.
 hsc: significant wave height, C altimeter band.
 wnd: 10-meter wind speed.
 'cal' means calibrated by IMOS-AODN.

DEPENDENCIES:
 See setup.py and the imports below.
 AODN altimeter data previously downloaded (see wfetchsatellite_AODN_Altimeter.sh)
 gridInfo.nc, generated by preprGridMask.py
  pay attention to longitude standards (-180to180 or 0to360), corrected by shiftgrid

AUTHOR and DATE:
 04/04/2022: Ricardo M. Campos, first version.
 07/18/2022: Ricardo M. Campos, SENTINEL-3B included. Longitude standard checked.

PERSON OF CONTACT:
 Ricardo M Campos: ricardo.campos@noaa.gov

"""

import numpy as np
from matplotlib.mlab import *
from pylab import *
import os
import netCDF4 as nc
import pyresample
from mpl_toolkits.basemap import shiftgrid
import time
from calendar import timegm
import sys
import warnings; warnings.filterwarnings("ignore")
# netcdf format
fnetcdf="NETCDF4"

# number of procs for parallelization
npcs=5
# power of initial array 10**pia (size) that will be used to allocate satellite data (faster than append)
pia=10
# Maximum distance (m) for pyresample weighted average
dlim=25000.
# Maximum temporal distance (s) for pyresample weighted average
maxti=1800.
# Directory where AODN altimeter data is saved, downloaded using wfetchsatellite_AODN_Altimeter.sh
dirs='/data/satellite/AODN_altm'
# Date interval
datemin='2000010100'; datemax='2021123123'

# Satellite missions available at AODN dataset, pick one as this code runs one satellite at a time!
s=np.int(sys.argv[1]) # argument satellite ID for satellite mission selection. s=0 is JASON3, s=1 is JASON2 etc. See list below.
sdname=np.array(['JASON3','JASON2','CRYOSAT2','JASON1','HY2','SARAL','SENTINEL3A','ENVISAT','ERS1','ERS2','GEOSAT','GFO','TOPEX','SENTINEL3B'])
sname=np.array(['JASON-3','JASON-2','CRYOSAT-2','JASON-1','HY-2','SARAL','SENTINEL-3A','ENVISAT','ERS-1','ERS-2','GEOSAT','GFO','TOPEX','SENTINEL-3B'])

# Quality Control parameters
max_swh_rms = 1.5  # Max RMS of the band significant wave height
max_sig0_rms = 0.8 # Max RMS of the backscatter coefficient
max_swh_qc = 2.0 # Max SWH Ku band quality control
hsmax=20.; wspmax=60.
min_swh_numval = np.array([17,17,17,17,17,17,17,17,17,17,-inf,3,7,17])

# weight function for pyresample
def wf(pdist):
	a=(1 - pdist / (dlim+1))
	return (abs(a)+a)/2

# Mask with lat lon arrays you want to collocate the altimeter data into. Generated by preprGridMask.py
f=nc.Dataset('gridInfo.nc')
latm=f.variables['latitude'][:]; lonm=f.variables['longitude'][:]
mask=f.variables['mask'][:,:]; f.close(); del f
mask,lonm = shiftgrid(180.,mask,lonm,start=False)

# Sat files (squares) considering the domain (latm lonm) of interest, for the AODN file names
auxlat=np.array(np.arange(-90.,90.+1.,1)).astype('int')
auxlon=np.array(np.arange(0.,360.+1,1)).astype('int')

# Pyresample target points (latm lonm for valid water points).
NEWLON, NEWLAT = meshgrid(lonm,latm)
ind=np.where(mask>0); flatm = np.array(NEWLAT[ind]); flonm = np.array(NEWLON[ind]); del NEWLON, NEWLAT; del ind
targ_def = pyresample.geometry.SwathDefinition(lons=flonm,lats=flatm)

# Read and allocate satellite data into arrays
ast=np.double(np.zeros((10**pia),'d')); aslat=np.zeros((10**pia),'f'); aslon=np.zeros((10**pia),'f');
ahsk=np.zeros((10**pia),'f'); ahskcal=np.zeros((10**pia),'f'); ahsc=np.zeros((10**pia),'f');
awnd=np.zeros((10**pia),'f'); awndcal=np.zeros((10**pia),'f'); asig0knstd=np.zeros((10**pia),'f');
aswhknobs=np.zeros((10**pia),'f'); aswhknstd=np.zeros((10**pia),'f'); aswhkqc=np.zeros((10**pia),'f')
ii=0
for j in auxlat:
	for k in auxlon:

		if j>=0:
			hem='N'
		else:
			hem='S'

		try: 
			fu=nc.Dataset(dirs+'/'+sdname[s]+'/IMOS_SRS-Surface-Waves_MW_'+sname[s]+'_FV02_'+str(np.abs(j)).zfill(3)+hem+'-'+str(k).zfill(3)+'E-DM00.nc')
		except:
			print(dirs+'/'+sdname[s]+'/IMOS_SRS-Surface-Waves_MW_'+sname[s]+'_FV02_'+str(np.abs(j)).zfill(3)+hem+'-'+str(k).zfill(3)+'E-DM00.nc does not exist'); vai=0
		else:
			st=np.double(fu.variables['TIME'][:])
			if size(st)>10:
				slat=fu.variables['LATITUDE'][:]
				slon=fu.variables['LONGITUDE'][:]
				hsc=fu.variables['SWH_C'][:]
				wnd=fu.variables['WSPD'][:]
				wndcal=fu.variables['WSPD_CAL'][:]
				try: 
					hsk=fu.variables['SWH_KU'][:]
					hskcal=fu.variables['SWH_KU_CAL'][:]
					sig0knstd=fu.variables['SIG0_KU_std_dev'][:]
					swhknobs=fu.variables['SWH_KU_num_obs'][:]
					swhknstd=fu.variables['SWH_KU_std_dev'][:]
					swhkqc=fu.variables['SWH_KU_quality_control'][:]
				except:
					print(' error reading KU, pick KA')
					hsk=fu.variables['SWH_KA'][:]
					hskcal=fu.variables['SWH_KA_CAL'][:]
					sig0knstd=fu.variables['SIG0_KA_std_dev'][:]
					swhknobs=fu.variables['SWH_KA_num_obs'][:]
					swhknstd=fu.variables['SWH_KA_std_dev'][:]
					swhkqc=fu.variables['SWH_KA_quality_control'][:]

				if ii+size(st) <= ast.shape[0] :
					if (st.shape[0]==wnd.shape[0]) & (slat.shape[0]==slon.shape[0]) & (hsk.shape[0]==hskcal.shape[0]) :	
						ast[ii:ii+st.shape[0]]=np.array(st).astype('double')
						aslat[ii:ii+st.shape[0]]=np.array(slat).astype('float')
						aslon[ii:ii+st.shape[0]]=np.array(slon).astype('float')
						ahsk[ii:ii+st.shape[0]]=np.array(hsk).astype('float')
						ahskcal[ii:ii+st.shape[0]]=np.array(hskcal).astype('float')
						ahsc[ii:ii+st.shape[0]]=np.array(hsc).astype('float')
						awnd[ii:ii+st.shape[0]]=np.array(wnd).astype('float')
						awndcal[ii:ii+st.shape[0]]=np.array(wndcal).astype('float')
						asig0knstd[ii:ii+st.shape[0]]=np.array(sig0knstd).astype('float')
						aswhknobs[ii:ii+st.shape[0]]=np.array(swhknobs).astype('float')
						aswhknstd[ii:ii+st.shape[0]]=np.array(swhknstd).astype('float')
						aswhkqc[ii:ii+st.shape[0]]=np.array(swhkqc).astype('float')
						ii=ii+st.shape[0]

				else:
					sys.exit('Small array to allocate the satellite data! Increase the power of initial array (pia)')

				del st,slat,slon,hsk,hskcal,hsc,wnd,sig0knstd,swhknobs,swhknstd,swhkqc
				fu.close(); del fu

print(' Done reading and allocating satellite data '+sdname[s])
del ii

adatemin= np.double(  (timegm( time.strptime(datemin, '%Y%m%d%H') )-float(timegm( time.strptime('1985010100', '%Y%m%d%H') ))) /(24.*3600.) )
adatemax= np.double(  (timegm( time.strptime(datemax, '%Y%m%d%H') )-float(timegm( time.strptime('1985010100', '%Y%m%d%H') ))) /(24.*3600.) )

# Quality Control Check ----
indq = np.where( (aswhknstd<=max_swh_rms) & (asig0knstd<=max_sig0_rms) & (aswhknobs>=min_swh_numval[s]) & (aswhkqc<=max_swh_qc) & (ahsk>0.01) & (ahsk<hsmax) & (awnd>0.01) & (awnd<wspmax) & (ast>=adatemin) & (ast<=adatemax) )     
del asig0knstd,aswhknobs,aswhknstd,aswhkqc,adatemin,adatemax

if size(indq)>10:
	ii=0
	ast=np.double(np.copy(ast[indq[0]]))
	ast=np.double(np.copy(ast)*24.*3600.+float(timegm( time.strptime('1985010100', '%Y%m%d%H') )))
	aslat=np.copy(aslat[indq[0]]); aslon=np.copy(aslon[indq[0]])
	ahsk=np.copy(ahsk[indq[0]]); ahskcal=np.copy(ahskcal[indq[0]]); ahsc=np.copy(ahsc[indq[0]])
	awnd=np.copy(awnd[indq[0]]); awndcal=np.copy(awndcal[indq[0]])
	# Collocated Arrays:
	# final hourly time array. Combined with flatm and flonm, it represents the reference for sat collocation
	atime = np.array(np.arange(np.double((np.round(ast.min()/3600.)*3600.)-3600.),np.double((np.round(ast.max()/3600.)*3600.)+3600.)+1,3600.)).astype('double')
	#
	ftime=np.double(np.zeros((ast.shape[0]*2),'d')); flat=np.zeros((ast.shape[0]*2),'f'); flon=np.zeros((ast.shape[0]*2),'f')
	fhsk=np.zeros((ast.shape[0]*2),'f'); stdhsk=np.zeros((ast.shape[0]*2),'f'); counthsk=np.zeros((ast.shape[0]*2),'f')
	fhskcal=np.zeros((ast.shape[0]*2),'f'); fhsc=np.zeros((ast.shape[0]*2),'f') 
	fwnd=np.zeros((ast.shape[0]*2),'f'); fwndcal=np.zeros((ast.shape[0]*2),'f')

	# into the regular grid with pyresample kd tree
	for t in range(0,atime.shape[0]):
		indt = np.where( abs(ast[:]-atime[t]) < maxti )
		if size(indt)>2:
			prlon=np.copy(aslon[indt[0]]); prlon[prlon>180.]=prlon[prlon>180.]-360.
			orig_def = pyresample.geometry.SwathDefinition(lons=prlon, lats=aslat[indt[0]]); del prlon
			# By distance function wf
			auxfhsk, auxstdhsk, auxcounthsk = pyresample.kd_tree.resample_custom(orig_def,ahsk[indt[0]],targ_def,radius_of_influence=dlim,weight_funcs=wf,fill_value=0,with_uncert=True,nprocs=npcs)
			auxfhskcal = pyresample.kd_tree.resample_custom(orig_def,ahskcal[indt[0]],targ_def,radius_of_influence=dlim,weight_funcs=wf,fill_value=0,nprocs=npcs)
			auxfhsc = pyresample.kd_tree.resample_custom(orig_def,ahsc[indt[0]],targ_def,radius_of_influence=dlim,weight_funcs=wf,fill_value=0,nprocs=npcs)
			auxfwnd = pyresample.kd_tree.resample_custom(orig_def,awnd[indt[0]],targ_def,radius_of_influence=dlim,weight_funcs=wf,fill_value=0,nprocs=npcs)
			auxfwndcal = pyresample.kd_tree.resample_custom(orig_def,awndcal[indt[0]],targ_def,radius_of_influence=dlim,weight_funcs=wf,fill_value=0,nprocs=npcs)
			# print('   - ok '+repr(t))
			indpqq = np.where( (auxfhskcal>0.01) & (auxfwnd>0.01) & (auxfhskcal<hsmax) & (auxfwnd<wspmax) )[0]
			# allocate data into final array
			ftime[ii:ii+size(indpqq)] = np.array(np.zeros(size(indpqq),'d')+atime[t]).astype('double')
			flat[ii:ii+size(indpqq)] = np.array(flatm[indpqq]).astype('float')
			flon[ii:ii+size(indpqq)] = np.array(flonm[indpqq]).astype('float')
			fhsk[ii:ii+size(indpqq)] = np.array(auxfhsk[indpqq]).astype('float')
			stdhsk[ii:ii+size(indpqq)] = np.array(auxstdhsk[indpqq]).astype('float')
			counthsk[ii:ii+size(indpqq)] = np.array(auxcounthsk[indpqq]).astype('float')
			fhskcal[ii:ii+size(indpqq)] = np.array(auxfhskcal[indpqq]).astype('float')
			fhsc[ii:ii+size(indpqq)] = np.array(auxfhsc[indpqq]).astype('float')
			fwnd[ii:ii+size(indpqq)] = np.array(auxfwnd[indpqq]).astype('float')
			fwndcal[ii:ii+size(indpqq)] = np.array(auxfwndcal[indpqq]).astype('float')
			ii=ii+size(indpqq)

			del auxfhsk, auxstdhsk, auxcounthsk, auxfhskcal, auxfhsc, auxfwnd, auxfwndcal, indpqq
				
		del indt
		print('PyResample kdtree, hourly time, '+repr(t))

	del ast, aslat, aslon, ahsk, ahskcal, ahsc, awnd, awndcal, indq, atime

	print(' '); print(sdname[s]+' Done')

	# Final quality control (double check)
	ind=np.where( (fhsk<0.01) | (fhsk>hsmax) )
	if np.any(ind):
		fhsk[ind[0]]=np.nan; del ind

	ind=np.where( (fhskcal<0.01) | (fhskcal>hsmax) )
	if np.any(ind):
		fhskcal[ind[0]]=np.nan; del ind

	ind=np.where( (fhsc<0.01) | (fhsc>hsmax) )
	if np.any(ind):
		fhsc[ind[0]]=np.nan; del ind

	ind=np.where( (fwnd<0.01) | (fwnd>wspmax) )
	if np.any(ind):
		fwnd[ind[0]]=np.nan; del ind

	ind=np.where( (fwndcal<0.01) | (fwndcal>wspmax) )
	if np.any(ind):
		fwndcal[ind[0]]=np.nan; del ind

	indf=np.where( (ftime>0.) & (fhsk>=0.0) )
	ftime=np.array(ftime[indf[0]]).astype('double')
	flat=np.array(flat[indf[0]]); flon=np.array(flon[indf[0]])
	fhsk=np.array(fhsk[indf[0]]); fhskcal=np.array(fhskcal[indf[0]])
	stdhsk=np.array(stdhsk[indf[0]]); counthsk=np.array(counthsk[indf[0]])
	fhsc=np.array(fhsc[indf[0]])
	fwnd=np.array(fwnd[indf[0]]); fwndcal=np.array(fwndcal[indf[0]])
	print(sdname[s]+' .  Array Size '+np.str(size(indf))); print(' ')
	del indf

	# Save netcdf
	ncfile = nc.Dataset('AltimeterGridded_'+sdname[s]+'.nc', "w", format=fnetcdf) 
	ncfile.history="AODN Altimeter data on regular grid." 
	# create  dimensions.
	ncfile.createDimension('time' , ftime.shape[0] )
	# create variables.
	vflat = ncfile.createVariable('latitude',np.dtype('float32').char,('time'))
	vflon = ncfile.createVariable('longitude',np.dtype('float32').char,('time'))
	vft = ncfile.createVariable('stime',np.dtype('float64').char,('time'))
	vfhsk = ncfile.createVariable('hsk',np.dtype('float32').char,('time'))
	vstdhsk = ncfile.createVariable('stdhsk',np.dtype('float32').char,('time'))
	vcounthsk = ncfile.createVariable('counthsk',np.dtype('float32').char,('time'))
	vfhskcal = ncfile.createVariable('hskcal',np.dtype('float32').char,('time'))
	vfhsc = ncfile.createVariable('hsc',np.dtype('float32').char,('time'))
	vfwnd = ncfile.createVariable('wnd',np.dtype('float32').char,('time'))
	vfwndcal = ncfile.createVariable('wndcal',np.dtype('float32').char,('time'))
	# Assign units
	vft.units = 'seconds since 1970-01-01 00:00:00'
	vflat.units = 'degrees_north' ; vflon.units = 'degrees_east'
	vfwnd.units = 'm/s' ; vfwndcal.units = 'm/s'
	vfhsk.units = 'm'; vfhskcal.units = 'm'; vfhsc.units = 'm'
	# Allocate Data
	vflat[:] = flat; vflon[:] = flon; vft[:] = ftime
	vfhsk[:] = fhsk; vstdhsk[:] = stdhsk; vcounthsk[:] = counthsk
	vfhskcal[:] = fhskcal; vfhsc[:] = fhsc
	vfwnd[:] = fwnd; vfwndcal[:] = fwndcal
	ncfile.close()
	print(' ')
	print('netcdf ok ')

	del vft, vflat, vflon, vfhsk, vstdhsk, vcounthsk, vfhskcal, vfhsc, vfwnd, vfwndcal

else:
	sys.exit(' No satellite records within the given time/date range and quality control parameters selected.')


