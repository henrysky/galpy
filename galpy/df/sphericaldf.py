# Superclass for spherical distribution functions, contains
#   - sphericaldf: superclass of all spherical DFs
#   - isotropicsphericaldf: superclass of all isotropic spherical DFs
#   - anisotropicsphericaldf: superclass of all anisotropic spherical DFs
#
# To implement a new DF do something like:
#   - Inherit from isotropicsphericaldf for an isotropic DF and implement
#     fE(self,E) which returns the DF as a function of E (see kingdf), then
#     you should be set! You may also have to implement _vmax_at_r(self,pot,r)
#     when the maximum velocity at a given position is less than the escape
#     velocity
#   - Inherit from anisotropicsphericaldf for an anisotropic DF, then you need
#     to implement a bunch of functions:
#       * _call_internal(self,*args,**kwargs): which returns the DF as a
#                                              function of (E,L,Lz)
#       * _sample_eta(self,n=1): to sample the velocity angle
#       * _p_v_at_r(self,v,r): whcih returns p(v|r)
#     constantbetadf is an example of this
#
#  Note that we may have to re-think the implementation of anisotropic DFs to
#  allow more general forms such as Osipkov-Merritt...
#
import warnings
import numpy
import scipy.interpolate
from scipy import integrate, special
from .df import df
from ..potential import evaluatePotentials, vesc
from ..potential.SCFPotential import _xiToR
from ..orbit import Orbit
from ..util import conversion, galpyWarning
from ..util.conversion import physical_conversion
if conversion._APY_LOADED:
    from astropy import units

class sphericaldf(df):
    """Superclass for spherical distribution functions"""
    def __init__(self,pot=None,scale=None,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initializes a spherical DF

        INPUT:

           pot= (None) Potential instance or list thereof

           scale= (None) length-scale parameter to be used internally

           ro= ,vo= galpy unit parameters

        OUTPUT:

            None

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        df.__init__(self,ro=ro,vo=vo)
        if not conversion.physical_compatible(self,pot):
            raise RuntimeError("Unit-conversion parameters of input potential incompatible with those of the DF instance")
        phys= conversion.get_physical(pot,include_set=True)
        # if pot has physical units, transfer them (if already on, we know
        # they are compaible)
        if phys['roSet'] and phys['voSet']:
            self.turn_physical_on(ro=phys['ro'],vo=phys['vo'])
        if pot is None: # pragma: no cover
            raise IOError("pot= must be set")
        self._pot = pot
        try:
            self._scale = pot._scale
        except AttributeError:
            self._scale= conversion.parse_length(scale,ro=self._ro) \
                if scale is not None else 1.

############################## EVALUATING THE DF###############################
    @physical_conversion('phasespacedensity',pop=True)
    def __call__(self,*args,**kwargs):
        """
        NAME:

            __call__

        PURPOSE:

            return the DF

        INPUT:

            Either:

                a) (E,L,Lz): tuple of E and (optionally) L and (optionally) Lz.
                    Each may be Quantity
                    
                b) R,vR,vT,z,vz,phi: 

                c) Orbit instance: orbit.Orbit instance and if specific time 
                    then orbit.Orbit(t) 

        OUTPUT:

            Value of DF

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        # Get E,L,Lz
        if len(args) == 1:
            if not isinstance(args[0],Orbit): # Assume tuple (E,L,Lz)
                E,L,Lz= (args[0]+(None,None))[:3]
            else: # Orbit
                E = args[0].E(pot=self._pot,use_physical=False)
                L = numpy.sqrt(numpy.sum(args[0].L(use_physical=False)**2.))
                Lz = args[0].Lz(use_physical=False)
            E= numpy.atleast_1d(conversion.parse_energy(E,vo=self._vo))
            L= numpy.atleast_1d(conversion.parse_angmom(L,ro=self._ro,
                                                        vo=self._vo))
            Lz= numpy.atleast_1d(conversion.parse_angmom(Lz,ro=self._vo,
                                                         vo=self._vo))
        else: # Assume R,vR,vT,z,vz,(phi)
            R,vR,vT,z,vz, phi = (args+(None,))[:6]
            R= conversion.parse_length(R,ro=self._ro)
            vR= conversion.parse_velocity(vR,vo=self._vo)
            vT= conversion.parse_velocity(vT,vo=self._vo)
            z= conversion.parse_length(z,ro=self._ro)
            vz= conversion.parse_velocity(vz,vo=self._vo)
            vtotSq = vR**2.+vT**2.+vz**2.
            E= numpy.atleast_1d(0.5*vtotSq
                                +evaluatePotentials(self._pot,R,z,
                                                    use_physical=False))
            Lz = numpy.atleast_1d(R*vT)
            r = numpy.sqrt(R**2.+z**2.)
            vrad = (R*vR+z*vz)/r
            L = numpy.atleast_1d(numpy.sqrt(vtotSq-vrad**2.)*r)
        return self._call_internal(E,L,Lz) # Some function for each sub-class

    def vmomentdensity(self,r,n,m,**kwargs):
        """
        NAME:

           vmomentdensity

        PURPOSE:

           calculate an arbitrary moment of the velocity distribution 
           at r times the density

        INPUT:

           r - spherical radius at which to calculate the moment

           n - vr^n, where vr = v x cos eta

           m - vt^m, where vt = v x sin eta

        OUTPUT:

           <vr^n vt^m x density> at r

        HISTORY:
         
            2020-09-04 - Written - Bovy (UofT)
        """
        r= conversion.parse_length(r,ro=self._ro)
        use_physical= kwargs.pop('use_physical',True)
        ro= kwargs.pop('ro',None)
        if ro is None and hasattr(self,'_roSet') and self._roSet:
            ro= self._ro
        ro= conversion.parse_length_kpc(ro)
        vo= kwargs.pop('vo',None)
        if vo is None and hasattr(self,'_voSet') and self._voSet:
            vo= self._vo
        vo= conversion.parse_velocity_kms(vo)
        if use_physical and not vo is None and not ro is None:
            fac= vo**(n+m)/ro**3
            if conversion._APY_UNITS:
                u= 1/units.kpc**3*(units.km/units.s)**(n+m)
            out= self._vmomentdensity(r,n,m)
            if conversion._APY_UNITS:
                return units.Quantity(out*fac,unit=u)
            else:
                return out*fac
        else:
            return self._vmomentdensity(r,n,m)

    def _vmomentdensity(self,r,n,m):
        return 2.*numpy.pi\
            *integrate.dblquad(lambda eta,v: v**(2.+m+n)
                               *numpy.sin(eta)**(1+m)*numpy.cos(eta)**n
                               *self(r,v*numpy.cos(eta),v*numpy.sin(eta),0.,0.,
                                     use_physical=False),
                               0.,self._vmax_at_r(self._pot,r),
                               lambda x: 0.,lambda x: numpy.pi)[0]
    
    @physical_conversion('velocity',pop=True)
    def sigmar(self,r):
        """
        NAME:

           sigmar

        PURPOSE:

           calculate the radial velocity dispersion at radius r

        INPUT:

           r - spherical radius at which to calculate the radial velocity dispersion

        OUTPUT:

           sigma_r(r)

        HISTORY:
         
            2020-09-04 - Written - Bovy (UofT)
        """
        r= conversion.parse_length(r,ro=self._ro)
        return numpy.sqrt(self._vmomentdensity(r,2,0)
                          /self._vmomentdensity(r,0,0))
    
    @physical_conversion('velocity',pop=True)
    def sigmat(self,r):
        """
        NAME:

           sigmar

        PURPOSE:

           calculate the tangential velocity dispersion at radius r

        INPUT:

           r - spherical radius at which to calculate the tangential velocity dispersion

        OUTPUT:

           sigma_t(r)

        HISTORY:
         
            2020-09-04 - Written - Bovy (UofT)
        """
        r= conversion.parse_length(r,ro=self._ro)
        return numpy.sqrt(self._vmomentdensity(r,0,2)
                          /self._vmomentdensity(r,0,0))

    def beta(self,r):
        """
        NAME:

           sigmar

        PURPOSE:

           calculate the anisotropy at radius r

        INPUT:

           r - spherical radius at which to calculate the anisotropy

        OUTPUT:

           beta(r)

        HISTORY:
         
            2020-09-04 - Written - Bovy (UofT)
        """
        return 1.-self.sigmat(r,use_physical=False)**2./2.\
            /self.sigmar(r,use_physical=False)**2.
    
############################### SAMPLING THE DF################################
    def sample(self,R=None,z=None,phi=None,n=1,return_orbit=True):
        """
        NAME:

            sample

        PURPOSE:

            Return full 6D samples of the DF

        INPUT:

            R= cylindrical radius at which to generate samples (can be Quantity)

            z= height at which to generate samples (can be Quantity)
            
            phi= azimuth at which to generate samples (can be Quantity)

            n= number of samples to generate

        OPTIONAL INPUT:

            return_orbit= (True) If True output is orbit.Orbit object, if False output is (R,vR,vT,z,vz,phi)

        OUTPUT:

            List of samples. Either vector (R,vR,vT,z,vz,phi) or orbit.Orbit

        NOTES:

            If R,z,phi are None then sample positions with CMF. If R,z,phi are 
            floats then sample n velocities at location. If array then sample 
            velocities at radii, ignoring n. phi can be None if R,z are set 
            by any above mechanism, will then sample phi for output.

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        if R is None or z is None: # Full 6D samples
            r = self._sample_r(n=n)
            phi,theta = self._sample_position_angles(n=n)
            R = r*numpy.sin(theta)
            z = r*numpy.cos(theta) 
        else: # 3D velocity samples
            R= conversion.parse_length(R,ro=self._ro)
            z= conversion.parse_length(z,ro=self._ro)
            if isinstance(R,numpy.ndarray):
                assert len(R) == len(z), \
                    """When R= is set to an array, z= needs to be set to """\
                    """an equal-length array"""
                n = len(R)
            else:
                R= R*numpy.ones(n)
                z= z*numpy.ones(n)
            r= numpy.sqrt(R**2.+z**2.)
            theta= numpy.arctan2(R,z)
            if phi is None: # Otherwise assume phi input type matches R,z
                phi,_ = self._sample_position_angles(n=n)
            else:
                phi= conversion.parse_angle(phi)
                phi= phi*numpy.ones(n) \
                    if not hasattr(phi,'__len__') or len(phi) < n \
                    else phi
        v = self._sample_v(r,n=n)
        eta,psi = self._sample_velocity_angles(n=n)
        vr = v*numpy.cos(eta)
        vtheta = v*numpy.sin(eta)*numpy.cos(psi)
        vT = v*numpy.sin(eta)*numpy.sin(psi)
        vR = vr*numpy.sin(theta) + vtheta*numpy.cos(theta)
        vz = vr*numpy.cos(theta) - vtheta*numpy.sin(theta)
        if return_orbit:
            o = Orbit(vxvv=numpy.array([R,vR,vT,z,vz,phi]).T)
            if self._roSet and self._voSet:
                o.turn_physical_on(ro=self._ro,vo=self._vo)
            return o
        else:
            return (R,vR,vT,z,vz,phi)

    def _sample_r(self,n=1):
        """Generate radial position samples from potential
        Note - the function interpolates the normalized CMF onto the variable 
        xi defined as:
        
        .. math:: \\xi = \\frac{r/a-1}{r/a+1}
        
        so that xi is in the range [-1,1], which corresponds to an r range of 
        [0,infinity)"""
        rand_mass_frac = numpy.random.uniform(size=n)
        if hasattr(self,'_icmf'):
            r_samples = self._icmf(rand_mass_frac)
        else:
            if not hasattr(self,'_xi_cmf_interpolator'):
                self._xi_cmf_interpolator= self._make_cmf_interpolator()
            xi_samples = self._xi_cmf_interpolator(rand_mass_frac)
            r_samples = _xiToR(xi_samples,a=self._scale)
        return r_samples

    def _make_cmf_interpolator(self):
        """Create the interpolator object for calculating radii from the CMF
        Note - must use self.xi_to_r() on any output of interpolator
        Note - the function interpolates the normalized CMF onto the variable 
        xi defined as:
        
        .. math:: \\xi = \\frac{r-1}{r+1}
        
        so that xi is in the range [-1,1], which corresponds to an r range of 
        [0,infinity)"""
        xis = numpy.arange(-1,1,1e-4)
        rs = _xiToR(xis,a=self._scale)
        # try/except necessary when mass doesn't take arrays, also need to
        # switch to a more general mass method at some point...
        #try: 
        ms = self._pot.mass(rs,use_physical=False)
        #except ValueError:
        #    ms= numpy.array([self._pot.mass(r,use_physical=False) for r in rs])
        ms/= self._pot.mass(numpy.inf,use_physical=False)
        # Add total mass point
        xis = numpy.append(xis,1)
        ms = numpy.append(ms,1)
        return scipy.interpolate.InterpolatedUnivariateSpline(ms,xis,k=3)

    def _sample_position_angles(self,n=1):
        """Generate spherical angle samples"""
        phi_samples = numpy.random.uniform(size=n)*2*numpy.pi
        theta_samples = numpy.arccos(1.-2*numpy.random.uniform(size=n))
        return phi_samples,theta_samples

    def _sample_v(self,r,n=1):
        """Generate velocity samples"""
        if not hasattr(self,'_v_vesc_pvr_interpolator'):
            self._v_vesc_pvr_interpolator = self._make_pvr_interpolator()
        return self._v_vesc_pvr_interpolator(\
                    numpy.log10(r/self._scale),numpy.random.uniform(size=n),
                    grid=False)*self._vmax_at_r(self._pot,r)

    def _sample_velocity_angles(self,n=1):
        """Generate samples of angles that set radial vs tangential 
        velocities"""
        eta_samples = self._sample_eta(n)
        psi_samples = numpy.random.uniform(size=n)*2*numpy.pi
        return eta_samples,psi_samples

    def _vmax_at_r(self,pot,r,**kwargs):
        """Function that gives the max velocity in the DF at r; 
        typically equal to vesc, but not necessarily for finite systems 
        such as King"""
        return vesc(pot,r,use_physical=False)
    
    def _make_pvr_interpolator(self, r_a_start=-3, r_a_end=3, 
                               r_a_interval=0.05, v_vesc_interval=0.01):
        """
        NAME:

        _make_pvr_interpolator

        PURPOSE:

        Calculate a grid of the velocity sampling function v^2*f(E) over many 
        radii. The radii are fractional with respect to some scale radius 
        which characteristically describes the size of the potential, 
        and the velocities are fractional with respect to the escape velocity 
        at each radius r. This information is saved in a 2D interpolator which 
        represents the inverse cumulative distribution at many radii. This 
        allows for sampling of v/vesc given an input r/a

        INPUT:

            r_a_start= radius grid start location in units of r/a

            r_a_end= radius grid end location in units of r/a

            r_a_interval= radius grid spacing in units of r/a

            v_vesc_interval= velocity grid spacing in units of v/vesc

        OUTPUT:

            None (But sets self._v_vesc_pvr_interpolator)

        HISTORY:

            Written 2020-07-24 - James Lane (UofT)
        """
        # Make an array of r/a by v/vesc and then calculate p(v|r)
        r_a_values = 10.**numpy.arange(r_a_start,r_a_end,r_a_interval)
        v_vesc_values = numpy.arange(0,1,v_vesc_interval)
        r_a_grid, v_vesc_grid = numpy.meshgrid(r_a_values,v_vesc_values)
        vesc_grid = self._vmax_at_r(self._pot,r_a_grid*self._scale)
        r_grid= r_a_grid*self._scale
        vr_grid= v_vesc_grid*vesc_grid
        # Calculate p(v|r) and normalize
        pvr_grid= self._p_v_at_r(vr_grid,r_grid)
        pvr_grid_cml = numpy.cumsum(pvr_grid,axis=0)
        pvr_grid_cml_norm = pvr_grid_cml\
        /numpy.repeat(pvr_grid_cml[-1,:][:,numpy.newaxis],pvr_grid_cml.shape[0],axis=1).T
        
        # Construct the inverse cumulative distribution on a regular grid
        n_new_pvr = 100 # Must be multiple of r_a_grid.shape[0]
        icdf_pvr_grid_reg = numpy.zeros((n_new_pvr,len(r_a_values)))
        icdf_v_vesc_grid_reg = numpy.zeros((n_new_pvr,len(r_a_values)))
        for i in range(pvr_grid_cml_norm.shape[1]):
            cml_pvr = pvr_grid_cml_norm[:,i]
            if numpy.any(cml_pvr < 0):
                warnings.warn("The DF appears to have negative regions; we'll try to ignore these for sampling the DF, but this may adversely affect the generated samples. Proceed with care!",galpyWarning)
            cml_pvr[cml_pvr < 0] = 0.
            start_indx= numpy.amax(numpy.arange(len(cml_pvr))[cml_pvr == numpy.amin(cml_pvr)])
            end_indx= numpy.amin(numpy.arange(len(cml_pvr))[cml_pvr == numpy.amax(cml_pvr)])+1
            cml_pvr_inv_interp = scipy.interpolate.InterpolatedUnivariateSpline(
                cml_pvr[start_indx:end_indx], v_vesc_values[start_indx:end_indx],k=3)
            pvr_samples_reg = numpy.linspace(0,1,n_new_pvr)
            v_vesc_samples_reg = cml_pvr_inv_interp(pvr_samples_reg)
            icdf_pvr_grid_reg[:,i] = pvr_samples_reg
            icdf_v_vesc_grid_reg[:,i] = v_vesc_samples_reg
        # Create the interpolator
        return scipy.interpolate.RectBivariateSpline(
            numpy.log10(r_a_grid[0,:]), icdf_pvr_grid_reg[:,0],
            icdf_v_vesc_grid_reg.T)

class isotropicsphericaldf(sphericaldf):
    """Superclass for isotropic spherical distribution functions"""
    def __init__(self,pot=None,scale=None,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initialize an isotropic distribution function

        INPUT:

           pot= (None) Potential instance or list thereof

           scale= scale parameter to be used internally

           ro=, vo= galpy unit parameters

        OUTPUT:
        
            None

        HISTORY:

            2020-09-02 - Written - Bovy (UofT)

        """
        sphericaldf.__init__(self,pot=pot,scale=scale,ro=ro,vo=vo)

    def _call_internal(self,*args):
        """
        NAME:

            _call_internal

        PURPOSE

            Calculate the distribution function for an isotropic DF

        INPUT:

            E,L,Lz - The energy, angular momemtum magnitude, and its z component (only E is used)

        OUTPUT:

            f(x,v) = f(E[x,v])

        HISTORY:

            2020-07 - Written - Lane (UofT)

        """
        return self.fE(args[0])

    def _vmomentdensity(self,r,n,m):
         if m%2 == 1 or n%2 == 1:
             return 0.
         return 2.*numpy.pi\
             *integrate.quad(lambda v: v**(2.+m+n)*
                             self.fE(evaluatePotentials(self._pot,r,0,
                                                        use_physical=False)
                                     +0.5*v**2.),
                             0.,self._vmax_at_r(self._pot,r))[0]\
            *special.gamma(m//2+1)*special.gamma(n//2+0.5)\
            /special.gamma(m//2+n//2+1.5)
         
    def _sample_eta(self,n=1):
        """Sample the angle eta which defines radial vs tangential velocities"""
        return numpy.arccos(1.-2.*numpy.random.uniform(size=n))

    def _p_v_at_r(self,v,r):
        return self.fE(evaluatePotentials(self._pot,r,0,use_physical=False)\
                       +0.5*v**2.)*v**2.
    
class anisotropicsphericaldf(sphericaldf):
    """Superclass for anisotropic spherical distribution functions"""
    def __init__(self,pot=None,scale=None,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initialize an anisotropic distribution function

        INPUT:

           pot= (None) Potential instance or list thereof

           scale= (None) length-scale parameter to be used internally

           ro= ,vo= galpy unit parameters

        OUTPUT:
        
            None

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        sphericaldf.__init__(self,pot=pot,scale=scale,ro=ro,vo=vo)
