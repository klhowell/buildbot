# This module enables ATOM and RSS feeds from webstatus.
#
# It is based on "feeder.py" which was part of the Buildbot
# configuration for the Subversion project. The original file was
# created by Lieven Gobaerts and later adjusted by API
# (apinheiro@igalia.coma) and also here
# http://code.google.com/p/pybots/source/browse/trunk/master/Feeder.py
#
# All subsequent changes to feeder.py where made by Chandan-Dutta
# Chowdhury <chandan-dutta.chowdhury @ hp.com> and Gareth Armstrong
# <gareth.armstrong @ hp.com>.
#
# Those modifications are as follows:
# 1) the feeds are usable from baseweb.WebStatus
# 2) feeds are fully validated ATOM 1.0 and RSS 2.0 feeds, verified
#    with code from http://feedvalidator.org
# 3) nicer xml output
# 4) feeds can be filtered as per the /waterfall display with the
#    builder and category filters
# 5) cleaned up white space and imports
#
# Finally, the code was directly integrated into these two files,
# buildbot/status/web/feeds.py (you're reading it, ;-)) and
# buildbot/status/web/baseweb.py.

import os
import re
import sys
import time
from twisted.web import resource
from buildbot.status.builder import SUCCESS, WARNINGS, FAILURE, EXCEPTION

class XmlResource(resource.Resource):
    contentType = "text/xml; charset=UTF-8"
    docType = ''
        
    def getChild(self, name, request):
        return self
    
    def render(self, request):
        data = self.content(request)
        request.setHeader("content-type", self.contentType)
        if request.method == "HEAD":
            request.setHeader("content-length", len(data))
            return ''
        return data

    def header (self, request):
        data = ('<?xml version="1.0" encoding="utf-8"?>\n')
        return data
    def footer(self, request):
        data = ''
        return data
    def content(self, request):
        data = self.docType
        data += self.header(request)
        data += self.body(request)
        data += self.footer(request)
        return data.encode( "utf-8" )
    def body(self, request):
        return ''

class FeedResource(XmlResource):
    title = None
    link = 'http://dummylink'
    language = 'en-us'
    description = 'Dummy rss'
    status = None

    def __init__(self, status, categories=None, title=None):
        self.status = status
        self.categories = categories
        self.title = title
        self.projectName = self.status.getProjectName()
        self.link = self.status.getBuildbotURL()
        self.description = 'List of FAILED builds'
        self.pubdate = time.gmtime(int(time.time()))
        self.user = self.getEnv(['USER', 'USERNAME'], 'buildmaster')
        self.hostname = self.getEnv(['HOSTNAME', 'COMPUTERNAME'],
                                    'buildmaster')
        self.children = {}

    def getEnv(self, keys, fallback):
        for key in keys:
            if key in os.environ:
                return os.environ[key]
        return fallback

    def getBuilds(self, request):
        builds = []
        # THIS is lifted straight from the WaterfallStatusResource Class in
        # status/web/waterfall.py
        #
        # we start with all Builders available to this Waterfall: this is
        # limited by the config-file -time categories= argument, and defaults
        # to all defined Builders.
        allBuilderNames = self.status.getBuilderNames(categories=self.categories)
        builders = [self.status.getBuilder(name) for name in allBuilderNames]

        # but if the URL has one or more builder= arguments (or the old show=
        # argument, which is still accepted for backwards compatibility), we
        # use that set of builders instead. We still don't show anything
        # outside the config-file time set limited by categories=.
        showBuilders = request.args.get("show", [])
        showBuilders.extend(request.args.get("builder", []))
        if showBuilders:
            builders = [b for b in builders if b.name in showBuilders]

        # now, if the URL has one or category= arguments, use them as a
        # filter: only show those builders which belong to one of the given
        # categories.
        showCategories = request.args.get("category", [])
        if showCategories:
            builders = [b for b in builders if b.category in showCategories]

        maxFeeds = 25

        # Copy all failed builds in a new list.
        # This could clearly be implemented much better if we had
        # access to a global list of builds.
        for b in builders:
            lastbuild = b.getLastFinishedBuild()
            if lastbuild is None:
                continue

            lastnr = lastbuild.getNumber()

            totalbuilds = 0
            i = lastnr
            while i >= 0:
                build = b.getBuild(i)
                i -= 1
                if not build:
                    continue

                results = build.getResults()

                # only add entries for failed builds!
                if results == FAILURE:
                    totalbuilds += 1
                    builds.append(build)

                # stop for this builder when our total nr. of feeds is reached
                if totalbuilds >= maxFeeds:
                    break

        # Sort build list by date, youngest first.
        if sys.version_info[:3] >= (2,4,0):
            builds.sort(key=lambda build: build.getTimes(), reverse=True)
        else:
            # If you need compatibility with python < 2.4, use this for
            # sorting instead:
            # We apply Decorate-Sort-Undecorate
            deco = [(build.getTimes(), build) for build in builds]
            deco.sort()
            deco.reverse()
            builds = [build for (b1, build) in deco]

        if builds:
            builds = builds[:min(len(builds), maxFeeds)]
        return builds

    def body (self, request):
        data = ''
        builds = self.getBuilds(request)

        for build in builds:
            start, finished = build.getTimes()
            finishedTime = time.gmtime(int(finished))
            link = re.sub(r'index.html', "", self.status.getURLForThing(build))

            # title: trunk r22191 (plus patch) failed on 'i686-debian-sarge1 shared gcc-3.3.5'
            ss = build.getSourceStamp()
            source = ""
            if ss.branch:
                source += "Branch %s " % ss.branch
            if ss.revision:
                source += "Revision %s " % str(ss.revision)
            if ss.patch:
                source += " (plus patch)"
            if ss.changes:
                pass
            if (ss.branch is None and ss.revision is None and ss.patch is None
                and not ss.changes):
                source += "Latest revision "
            got_revision = None
            try:
                got_revision = build.getProperty("got_revision")
            except KeyError:
                pass
            if got_revision:
                got_revision = str(got_revision)
                if len(got_revision) > 40:
                    got_revision = "[revision string too long]"
                source += "(Got Revision: %s)" % got_revision
            title = ('%s failed on "%s"' %
                     (source, build.getBuilder().getName()))

            # get name of the failed step and the last 30 lines of its log.
            if build.getLogs():
                log = build.getLogs()[-1]
                laststep = log.getStep().getName()
                try:
                    lastlog = log.getText()
                except IOError:
                    # Probably the log file has been removed
                    lastlog='<b>log file not available</b>'

            lines = re.split('\n', lastlog)
            lastlog = ''
            for logline in lines[max(0, len(lines)-30):]:
                lastlog = lastlog + logline + '<br/>'
            lastlog = lastlog.replace('\n', '<br/>')
            
            cxt = {}
            cxt['date'] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", finishedTime)
            cxt['project_url'] = self.link
            cxt['project_name'] = self.projectName
            cxt['builder_summary_link'] = ('%sbuilders/%s' %
                                           (self.link,
                                            build.getBuilder().getName()))            
            cxt['builder_name'] = build.getBuilder().getName()
            cxt['build_url'] = link
            cxt['build_number'] = build.getNumber()
            cxt['responsible_users'] = build.getResponsibleUsers()
            cxt['last_step'] = laststep
            
            template = request.site.buildbot_service.templates.get_template('feed_description.html')
            description = template.render(**cxt)

            data += self.item(title, description=description, lastlog=lastlog,
                              link=link, pubDate=finishedTime)

        return data

    def item(self, title='', link='', description='', pubDate=''):
        """Generates xml for one item in the feed."""

class Rss20StatusResource(FeedResource):
    def __init__(self, status, categories=None, title=None):
        FeedResource.__init__(self, status, categories, title)
        contentType = 'application/rss+xml'

    def header(self, request):
        data = FeedResource.header(self, request)
        
        cxt = {}
        cxt['title'] = self.title if self.title else ('Build status of ' + self.projectName)
        cxt['link'] = self.link
        cxt['root_link'] = re.sub(r'/index.html', '', self.link)
        cxt['language'] = self.language
        cxt['description'] = self.description
        if self.pubdate is not None:
            rfc822_pubdate = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                                           self.pubdate)
            cxt['rfc822_pubdate'] = rfc822_pubdate

        # store templates here as we don't have access to the request in item() 
        self.templates = request.site.buildbot_service.templates
        template = self.templates.get_template('feed_rss20_header.xml')
        data += template.render(**cxt)
        
        return data

    def item(self, title='', link='', description='', lastlog='', pubDate=''):
        cxt = {}
        cxt['title'] = title
        cxt['link'] = link
        if (description is not None and lastlog is not None):
            cxt['description'] = description
            cxt['lastlog'] = re.sub(r'<br/>', "\n", lastlog)

        if pubDate is not None:
            rfc822pubDate = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                                          pubDate)
            cxt['pub_date'] = rfc822pubDate
            
            # Every RSS item must have a globally unique ID
            guid = ('tag:%s@%s,%s:%s' % (self.user, self.hostname,
                                         time.strftime("%Y-%m-%d", pubDate),
                                         time.strftime("%Y%m%d%H%M%S",
                                                       pubDate)))
            cxt['guid'] = guid

        template = self.templates.get_template('feed_rss20_item.xml')
        return template.render(**cxt)
        
    def footer(self, request):
        return self.templates.get_template('feed_rss20_footer.xml').render()

class Atom10StatusResource(FeedResource):
    def __init__(self, status, categories=None, title=None):
        FeedResource.__init__(self, status, categories, title)
        contentType = 'application/atom+xml'

    def header(self, request):
        data = FeedResource.header(self, request)
        cxt = {}
        cxt['link'] = self.link
        cxt['title'] = self.title if self.title else 'Build status of ' + self.projectName
        cxt['description'] = self.description
        if self.pubdate is not None:
            cxt['rfc3339_pubdate'] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                   self.pubdate)

        # allow item() to access templates
        self.templates = request.site.buildbot_service.templates
        template = self.templates.get_template('feed_atom10_header.xml')
        data += template.render(**cxt)
        return data

    def item(self, title='', link='', description='', lastlog='', pubDate=''):

        cxt = {'title': title, 'link': link }
        
        if (description is not None and lastlog is not None):
            cxt['lastlog'] = re.sub(r'<br/>', "\n", lastlog)
            cxt['description'] = description
        if pubDate is not None:
            cxt['rfc3339_pubdate'] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                           pubDate)
            cxt['guid'] = ('tag:%s@%s,%s:%s' % (self.user, self.hostname,
                                         time.strftime("%Y-%m-%d", pubDate),
                                         time.strftime("%Y%m%d%H%M%S",
                                                       pubDate)))
        template = self.templates.get_template('feed_atom10_item.xml')        
        return template.render(**cxt)

    def footer(self, request):
        template = self.templates.get_template('feed_atom10_footer.xml')        
        return template.render()
