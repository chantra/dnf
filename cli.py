#!/usr/bin/python -t
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# Copyright 2004 Duke University 

import os
import sys
import time
import getopt
import random
import fcntl
import fnmatch
import re
import output

import progress_meter
import yum
import yum.yumcomps
import yum.Errors
import yum.misc
from rpmUtils.miscutils import compareEVR
from yum.packages import parsePackages, returnBestPackages

from yum.logger import Logger
from yum.config import yumconf
from i18n import _

__version__ = '2.1.0'


class YumBaseCli(yum.YumBase):
    """Inherits from yum.YumBase this is the base class for yum cli."""
    def __init__(self):
        yum.YumBase.__init__(self)
        
    def doRepoSetup(self):
        """grabs the repomd.xml for each enabled repository and sets up the basics
           of the repository"""
           
        for repo in self.repos.listEnabled():
            self.log(2, 'Setting up Repo:  %s' % repo)
            try:
                repo.dirSetup(cache=self.conf.getConfigOption('cache'))
            except yum.Errors.RepoError, e:
                self.errorlog(0, '%s' % e)
                sys.exit(1)
            try:
                repo.getRepoXML(cache=self.conf.getConfigOption('cache'))
            except yum.Errors.RepoError, e:
                self.errorlog(0, 'Cannot open/read repomd.xml file for repository: %s' % repo)
                sys.exit(1)
        self.doSackSetup(callback=output.simpleProgressBar)
    
    def doGroupSetup(self):
        """determines which repos have groups and builds the groups lists"""
        
        self.grpInfo = yum.yumcomps.Groups_Info(self.rpmdb.getPkgList(),
                                 self.conf.getConfigOption('overwrite_groups'))
                                 
        for repo in self.repos.listGroupsEnabled():
            groupfile = repo.getGroups(self.conf.getConfigOption('cache'))
            if groupfile:
                self.log(4, 'Group File found for %s' % repo)
                self.log(4, 'Adding Groups from %s' % repo)
                self.grpInfo.add(groupfile)

        if self.grpInfo.compscount > 0:
            self.grpInfo.compileGroups()
        else:
            self.errorlog(0, _('No groups provided or accessible on any repository.'))
            self.errorlog(1, _('Exiting.'))
            sys.exit(1)
        
    def getOptionsConfig(self, args):
        """parses command line arguments, takes cli args:
        sets up self.conf and self.cmds as well as logger objects 
        in base instance"""
        
        # setup our errorlog object 
        self.errorlog = Logger(threshold=2, file_object=sys.stderr)
    
        # our default config file location
        yumconffile = None
        if os.access("/etc/yum.conf", os.R_OK):
            yumconffile = "/etc/yum.conf"
    
        try:
            gopts, self.cmds = getopt.getopt(args, 'tCc:hR:e:d:y', ['help',
                                                            'version',
                                                            'installroot=',
                                                            'enablerepo=',
                                                            'disablerepo=',
                                                            'exclude=',
                                                            'obsoletes',
                                                            'download-only',
                                                            'tolerant'])
        except getopt.error, e:
            self.errorlog(0, _('Options Error: %s') % e)
            usage()
    
        # get the early options out of the way
        # these are ones that:
        #  - we need to know about and do NOW
        #  - answering quicker is better
        #  - give us info for parsing the others
        
        # our sleep variable for the random start time
        sleeptime=0
        
        try: 
            for o,a in gopts:
                if o == '--version':
                    print __version__
                    sys.exit(0)
                if o == '--installroot':
                    if os.access(a + "/etc/yum.conf", os.R_OK):
                        yumconffile = a + '/etc/yum.conf'
                if o == '-c':
                    yumconffile = a
    
            if yumconffile:
                try:
                    self.conf = yumconf(configfile = yumconffile)
                except yum.Errors.ConfigError, e:
                    self.errorlog(0, _('Config Error: %s.') % e)
                    sys.exit(1)
            else:
                self.errorlog(0, _('Cannot find any conf file.'))
                sys.exit(1)
                
            # config file is parsed and moving us forward
            # set some things in it.
                
            # who are we:
            self.conf.setConfigOption('uid', os.geteuid())

            # version of yum
            self.conf.setConfigOption('yumversion', __version__)
            
            
            # we'd like to have a log object now
            self.log=Logger(threshold=self.conf.getConfigOption('debuglevel'), file_object = 
                                                                        sys.stdout)
            
            # syslog-style log
            if self.conf.getConfigOption('uid') == 0:
                logfd = os.open(self.conf.getConfigOption('logfile'), os.O_WRONLY |
                                os.O_APPEND | os.O_CREAT)
                logfile =  os.fdopen(logfd, 'a')
                fcntl.fcntl(logfd, fcntl.F_SETFD)
                self.filelog = Logger(threshold = 10, file_object = logfile, 
                                preprefix = output.printtime())
            else:
                self.filelog = Logger(threshold = 10, file_object = None, 
                                preprefix = output.printtime())
            
        
            # now the rest of the options
            for o,a in gopts:
                if o == '-d':
                    self.log.threshold=int(a)
                    self.conf.setConfigOption('debuglevel', int(a))
                elif o == '-e':
                    self.errorlog.threshold=int(a)
                    self.conf.setConfigOption('errorlevel', int(a))
                elif o == '-y':
                    self.conf.setConfigOption('assumeyes',1)
                elif o in ['-h', '--help']:
                    self.usage()
                elif o == '-C':
                    self.conf.setConfigOption('cache', 1)
                elif o == '-R':
                    sleeptime = random.randrange(int(a)*60)
                elif o == '--obsoletes':
                    self.conf.setConfigOption('obsoletes', 1)
                elif o in ['-t', '--tolerant']:
                    self.conf.setConfigOption('tolerant', 1)
                elif o == '--installroot':
                    self.conf.setConfigOption('installroot', a)
                elif o == '--enablerepo':
                    try:
                        self.conf.repos.enableRepo(a)
                    except yum.Errors.ConfigError, e:
                        self.errorlog(0, _(e))
                        self.usage()
                elif o == '--disablerepo':
                    try:
                        self.conf.repos.disableRepo(a)
                    except yum.Errors.ConfigError, e:
                        self.errorlog(0, _(e))
                        self.usage()
                        
                elif o == '--exclude':
                    try:
                        excludelist = conf.getConfigOption('exclude')
                        excludelist.append(a)
                        self.conf.setConfigOption('exclude', excludelist)
                    except yum.Errors.ConfigError, e:
                        self.errorlog(0, _(e))
                        self.usage()
                
                            
        except ValueError, e:
            self.errorlog(0, _('Options Error: %s') % e)
            self.usage()
        
        # if we're below 2 on the debug level we don't need to be outputting
        # progress bars - this is hacky - I'm open to other options
        if self.conf.getConfigOption('debuglevel') < 2:
            self.conf.setConfigOption('progress_obj', None)
        else:
            self.conf.setConfigOption('progress_obj', progress_meter.text_progress_meter(fo=sys.stdout))
            
        # this is just a convenience reference
        self.repos = self.conf.repos
        
        # save our original args out
        self.args = args
        
        self.parseCommands() # before we exit check over the base command + args
                             # make sure they match
    
        # set our caching mode correctly
        
        if self.conf.getConfigOption('uid') != 0:
            self.conf.setConfigOption('cache', 1)
        # run the sleep - if it's unchanged then it won't matter
        time.sleep(sleeptime)                        


    def parseCommands(self):
        """reads self.cmds and parses them out to make sure that the requested 
        base command + argument makes any sense at all""" 
    
        if len(self.conf.getConfigOption('commands')) == 0 and len(self.cmds) < 1:
            self.cmds = self.conf.getConfigOption('commands')
        else:
            self.conf.setConfigOption('commands', self.cmds)
        if len(self.cmds) < 1:
            self.errorlog(0, _('You need to give some command'))
            self.usage()

        self.basecmd = self.cmds[0] # our base command
        self.extcmds = self.cmds[1:] # out extended arguments/commands
        
        if self.basecmd not in ('update', 'install','info', 'list', 'erase',\
                                'grouplist', 'groupupdate', 'groupinstall',\
                                'clean', 'remove', 'provides', 'check-update',\
                                'search'):
            self.usage()
            
    
        if self.conf.getConfigOption('uid') != 0:
            if self.basecmd in ['install', 'update', 'clean', 'upgrade','erase', 
                                'groupupdate', 'groupinstall', 'remove',
                                'groupremove']:
                self.errorlog(0, _('You need to be root to perform these commands'))
                sys.exit(1)
        
        if self.basecmd in ['install', 'erase', 'remove']:
            if len(self.extcmds) == 0:
                self.errorlog(0, _('Error: Need to pass a list of pkgs to %s') % self.basecmd)
                self.usage()
    
        elif self.basecmd in ['provides', 'search']:       
            if len(self.extcmds) == 0:
                self.errorlog(0, _('Error: Need an item to match'))
                self.usage()
            
        elif self.basecmd in ['groupupdate', 'groupinstall', 'groupremove']:
            if len(self.extcmds) == 0:
                self.errorlog(0, _('Error: Need a group or list of groups'))
                self.usage()
    
        elif self.basecmd == 'clean':
            if len(self.extcmds) > 0 and self.extcmds[1] not in ['packages' 'headers', 'all']:
                self.errorlog(0, _('Error: Invalid clean option %s') % self.extcmds[1])
                self.usage()
    
        elif self.basecmd in ['list', 'check-update', 'info', 'update']:
            pass
    
        else:
            self.usage()

    def doCommands(self):
        """calls the base command passes the extended commands/args out to be
        parsed. (most notably package globs). returns a numeric result code and
        an optional string
           0 = we're done, exit
           1 = we've errored, exit with error string
           2 = we've got work yet to do, onto the next stage"""
        
        # at this point we know the args are valid - we don't know their meaning
        # but we know we're not being sent garbage
        
        if self.basecmd == 'install':
            return self.installPkgs()
        
        if self.basecmd in ['update', 'upgrade']:
            return self.updatePkgs()
            
        elif self.basecmd in ['erase', 'remove']:
            matched, unmatched = parsePackages(self.rpmdb.getPkgList(), 
                                               self.extcmds)
    
        elif self.basecmd ==  'list':
            try:
                return self.listPkgs()
            except yum.Errors.YumBaseError, e:
                return 1, '%s' % e
            
        elif self.basecmd == 'clean':
            # if we're cleaning then we don't need to talk to the net
            self.conf.setConfigOption('cache', 1)

    def installPkgs(self, userlist=None):
        """Attempts to take the user specified list of packages/wildcards
           and install them, or if they are installed, update them to a newer
           version. If a complete version number if specified, attempt to 
           downgrade them to the specified version"""
        # get the list of available packages
        # iterate over the user's list
        # add packages to Transaction holding class if they match.
        # if we've added any packages to the transaction then return 2 and a string
        # if we've hit a snag, return 1 and the failure explanation
        # if we've got nothing to do, return 0 and a 'nothing available to install' string
        if not userlist:
            userlist = self.extcmds
            
        self.doRpmDBSetup()
        installed = self.rpmdb.getPkgList()
        self.doRepoSetup()
        avail = self.pkgSack.simplePkgList()
        toBeInstalled = {} # keyed on name
        passToUpdate = [] # list of pkgtups to pass along to updatecheck

        for arg in userlist:
            arglist = [arg]
            exactmatch, matched, unmatched = parsePackages(avail, arglist)
            if len(unmatched) > 0: # if we get back anything in unmatched, it fails
                self.errorlog(0, _('No Match for argument %s') % arg)
                continue
            
            installable = yum.misc.unique(exactmatch + matched)
            exactarch = self.conf.getConfigOption('exactarch')
            
            # we look through each returned possibility and rule out the
            # ones that we obviously can't use
            for pkgtup in installable:
                (n, a, e, v, r) = pkgtup
                if a == 'src':
                    continue
                if pkgtup in installed:
                    continue

                # look up the installed packages based on name or name+arch, 
                # depending on exactarch being set.
                if exactarch:
                    installedByKey = self.rpmdb.returnTupleByKeyword(name=n, arch=a)
                else:
                    installedByKey = self.rpmdb.returnTupleByKeyword(name=n)
                
                
                # go through each package 
                if len(installedByKey) > 0:
                    for instTup in installedByKey:
                        (n2, a2, e2, v2, r2) = instTup
                        rc = compareEVR((e2, v2, r2), (e, v, r))
                        if rc < 0: # we're newer - this is an update, pass to them
                            passToUpdate.append(pkgtup)
                        elif rc == 0: # same, ignore
                            continue
                        elif rc > 0: # lesser, check if the pkgtup is an exactmatch
                                        # if so then add it to be installed,
                                        # the user explicitly wants this version
                                        # FIXME this is untrue if the exactmatch
                                        # does not include a version-rel section
                            if pkgtup in exactmatch:
                                if not toBeInstalled.has_key(n): toBeInstalled[n] = []
                                toBeInstalled[n].append(pkgtup)
                else: # we've not got any installed that match n or n+a
                    if not toBeInstalled.has_key(n): toBeInstalled[n] = []
                    toBeInstalled[n].append(pkgtup)
        
        #for n in toBeInstalled.keys():
        #    print '%s: ' % n,
        #    for tup in toBeInstalled[n]:
        #        print tup,
        #    print ''
        
        oldcount = self.tsInfo.count()
        pkglist = returnBestPackages(toBeInstalled)
        if len(pkglist) > 0:
            print 'reduced installs :'
        for (n,a,e,v,r) in pkglist:
            print '   %s.%s %s:%s-%s' % (n, a, e, v, r)
            self.tsInfo.add((n,a,e,v,r), 'i')

        if len(passToUpdate) > 0:
            print 'potential updates :'
        for (n,a,e,v,r) in passToUpdate:
            print '   %s.%s %s:%s-%s' % (n, a, e, v, r)
            
        if self.tsInfo.count() > oldcount:
            return 2, 'Package(s) to install'
        return 0, 'Nothing to do'
        
        #FIXME - what do I do in the case of yum install kernel\*
        # where kernel-1.1-1.i686 is installed and kernel-1.2-1.i[3456]86 are
        # available. the i686 kernel is an update, but the rest are potential
        # installs, right? Or in the event of one member of an arch being
        # an update all other members should be considered potential upgrades
        # unless the other member is also a multilib Arch.
        
    def updatePkgs(self, userlist=None):
        """take user commands and populate transaction wrapper with 
           packages to be updated"""
        if not userlist:
            userlist = self.extcmds
        
        # simple case - do them all
        self.doRpmDBSetup()
        installed = self.rpmdb.getPkgList()
        self.doRepoSetup()
        avail = self.pkgSack.simplePkgList()
        self.doUpdateSetup()
        updates = self.up.getUpdatesList()
        for pkgtup in updates:
            (n, a, e, v, r) = pkgtup
            self.tsInfo.add(pkgtup, 'u', 'user')
        
        return 2, 'Updated Packages in Transaction'
        
           
    def listPkgs(self, disp='output.rpm listDisplay'):
        """Generates the lists of packages based on arguments on the cli.
           calls out to a function for displaying the packages, that function
           is the second argument. Function takes a package object."""

        def sortPkgTup((n1, a1, e1, v1, r1) ,(n2, a2, e2, v2, r2)):
            """sorts a list of package tuples by name"""
            if n1 > n2:
                return 1
            elif n1 == n2:
                return 0
            else:
                return -1
        
            
        special = ['available', 'installed', 'all', 'extras', 'updates']
                   #'obsoletes', 'recent']

        installed = []
        available = []
        updates = []
        obsoletes = []
        recent = []
        extras = []
        pkgnarrow = 'all' # option used to narrow the subset of packages to
                          # list from
                        
        if len(self.extcmds) > 0:
            if self.extcmds[0] in special:
                pkgnarrow = self.extcmds.pop(0)

        if pkgnarrow == 'all':
            self.doRpmDBSetup()
            installed = self.rpmdb.getPkgList()
            self.doRepoSetup()
            avail = self.pkgSack.simplePkgList()
            for pkg in avail:
                if pkg not in installed:
                    available.append(pkg)
            del avail
            
        elif pkgnarrow == 'updates':
            self.doRpmDBSetup()
            self.doRepoSetup()
            self.doUpdateSetup()
            updates = self.up.getUpdatesList()

        elif pkgnarrow == 'installed':
            self.doRpmDBSetup()
            installed = self.rpmdb.getPkgList()
            
        elif pkgnarrow == 'available':
            self.doRpmDBSetup()
            self.doRepoSetup()
            avail = self.pkgSack.simplePkgList()
            inst = self.rpmdb.getPkgList()
            for pkg in avail:
                if pkg not in inst:
                    available.append(pkg)
            del avail

        elif pkgnarrow == 'extras':
            # we must compare the installed set versus the repo set
            # anything not in both is an 'extra'
            # put into totalpkgs list
            self.doRpmDBSetup()
            self.doRepoSetup()
            avail = self.pkgSack.simplePkgList()
            inst = self.rpmdb.getPkgList()
            for pkg in inst:
                if pkg not in avail:
                    extras.append(pkg)
            

        elif pkgnarrow == 'obsoletes':
            # get the list of obsoletes and list the available packages
            # that obsolete an installed package
            pass

        elif pkgnarrow == 'recent':
            # a miracle occurs - iterate throuh the pkgobjects
            # look for timestamp if it is in the last N days (lets say 2 weeks)
            # add it to the list
            pass

    # Iterate through the packages (after a simple sort by name), create
    # a package object for them and call the display function.
    # FIXME - for now just output some string

        thingslisted = 0
        for (lst, name) in [(updates, 'Updated'), (available, 'Available'), 
                            (installed, 'Installed'), (recent, 'Recently available'),
                            (obsoletes, 'Obsoleting'), (extras, 'Extra')]:
            if len(lst) > 0:
                if len(self.extcmds) > 0:
                    exactmatch, matched, unmatched = yum.packages.parsePackages(lst, self.extcmds)
                    lst = yum.misc.unique(matched + exactmatch)

        # check our reduced list
            if len(lst) > 0:
                thingslisted = 1
                self.log(2, '%s packages' % name)
                lst.sort(sortPkgTup)
                for pkg in lst:
                    (n, a, e, v, r) = pkg
                    self.log(2, '%s:%s-%s-%s.%s' % (e, n, v, r, a))

        if thingslisted == 0:
            self.errorlog(1, 'No Packages to list')
    
        return 0, 'Success'
    
    def userconfirm(self):
        """gets a yes or no from the user, defaults to No"""
        choice = raw_input('Is this ok [y/N]: ')
        if len(choice) == 0:
            return 1
        else:
            if choice[0] != 'y' and choice[0] != 'Y':
                return 1
            else:
                return 0        
                

    def usage(self):
        print _("""
        Usage:  yum [options] <update | install | info | remove | list |
                clean | provides | search | check-update | groupinstall | groupupdate |
                grouplist >
                    
            Options:
            -c [config file] - specify the config file to use
            -e [error level] - set the error logging level
            -d [debug level] - set the debugging level
            -y answer yes to all questions
            -t be tolerant about errors in package commands
            -R [time in minutes] - set the max amount of time to randomly run in.
            -C run from cache only - do not update the cache
            --installroot=[path] - set the install root (default '/')
            --version - output the version of yum
            -h, --help this screen
        """)
        sys.exit(1)

           


        

