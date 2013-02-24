# Imports for memcache
import pylibmc
from apps.common.util import get_memcache_client

# Template and context-related imports
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.db.models import Count
from django.http import HttpResponse

# eve_db models
from apps.market_data.models import Orders, OrderHistory
from eve_db.models import StaStation
from eve_db.models import MapRegion
from eve_db.models import MapSolarSystem

# JSON for the live search
from django.utils import simplejson

# Util
import datetime
import pytz
from operator import itemgetter

# Helper functions
from apps.market_data.sql import bid_ask_spread, import_markup
from apps.common.util import find_path
from django.db.models import Sum


# Caches this view 1 hour long
def ranking(request, group=0):

    """
    This function generates the station ranks based on active orders in the DB
    """

    # Connect to memcache
    mc = get_memcache_client()

    # Check if we already have a stored copy
    if (mc.get("e43-station-ranking") is not None):

        # Get values from mc if existent
        ranking = mc.get("e43-station-ranking")
        rank_list = ranking['rank_list']
        generated_at = ranking['generated_at']

    else:

        # Generate numbers if there is no cached version present in memcache (anymore)
        rank_list = Orders.active.values('stastation__id').annotate(ordercount=Count('id')).order_by('-ordercount')[:50]

        for rank in rank_list:
            station = StaStation.objects.get(id=rank['stastation__id'])
            rank.update({'system': station.solar_system, 'name':
                        station.name, 'region': station.region, 'id': station.id})

        generated_at = datetime.datetime.now()

        # Expire after an hour
        mc.set("e43-station-ranking", {'rank_list': rank_list, 'generated_at': generated_at}, time=3600)

    rcontext = RequestContext(request, {'rank_list': rank_list, 'generated_at': generated_at})

    return render_to_response('station/ranking.haml', rcontext)


def search(request):

    """
    Provides a search function to import tool.
    """

    # Get request
    if request.GET.get('query'):
        query = request.GET.get('query')
    else:
        query = ""

    # Only if the string is longer than 2 characters start looking in the DB
    if len(query) > 2:

        # Load published type objects matching the name
        systems = MapSolarSystem.objects.filter(name__icontains=query)

        # Load stations
        regions = MapRegion.objects.filter(name__icontains=query)

    # Create Context
    rcontext = RequestContext(
        request, {'systems': systems, 'regions': regions})

    # Render template
    return render_to_response('station/_import_search.haml', rcontext)


def live_search(request):

    """
    This adds a basic live search view to element43.
    The names in the invTypes table are searched with a case insensitive LIKE query and the result is returned as a JSON array of matching names.
    """

    if request.GET.get('query'):
        query = request.GET.get('query')
    else:
        query = ""

    # Prepare lists
    names = []
    ids = []

    # Default to empty array
    json = "{query:'" + query + "', suggestions:[], data:[]}"

    # Only if the string is longer than 2 characters start looking in the DB
    if len(query) > 2:

        # Load system objects matching the name
        systems = MapSolarSystem.objects.filter(name__icontains=query)

        for system in systems:
            names.append(system.name)
            ids.append('system_' + str(system.id))

        # Load regions
        regions = MapRegion.objects.filter(name__icontains=query)

        for region in regions:
            names.append(region.name)
            ids.append('region_' + str(region.id))

        # Add additional data for Ajax AutoComplete
        json = {'query': query, 'suggestions': names, 'data': ids}

        # Turn names into JSON
        json = simplejson.dumps(json)

    # Return JSON without using any template
    return HttpResponse(json, mimetype='application/json')


def station(request, station_id=60003760):

    """
    Shows station info.
    Defaults to Jita CNAP.
    """

    # The station id of Jita IV/4
    jita_cnap_id = 60003760

    # Get station object - default to CNAP if something goes wrong
    try:
        station = StaStation.objects.get(id=station_id)
    except:
        station_id = jita_cnap_id
        station = StaStation.objects.get(id=station_id)

    rcontext = RequestContext(request, {'station': station})

    return render_to_response('station/station.haml', rcontext)


def panel(request, station_id=60003760, group_id=1413):

    """
    Shows spread for market group.
    """

    # The station id of Jita IV/4
    jita_cnap_id = 60003760

    # Get station object - default to CNAP if something goes wrong
    try:
        station = StaStation.objects.get(id=station_id)
    except:
        station_id = jita_cnap_id
        station = StaStation.objects.get(id=station_id)

    # Get Bid/Ask Spread
    spread = bid_ask_spread(station_id, station.region_id, group_id)
    rcontext = RequestContext(request, {'station': station, 'spread': spread})

    return render_to_response('station/_panel.haml', rcontext)


def import_system(request, station_id=60003760, system_id=30000142):

    """
    Generates a list like http://goonmetrics.com/importing/
    Pattern: System -> Station
    """

    # Get system, station and markup
    system = MapSolarSystem.objects.get(id=system_id)
    station = StaStation.objects.get(id=station_id)

    # get the path to destination, assume trying for highsec route
    path = find_path(system_id, station.solar_system_id)
    numjumps = len(path) - 1 # don't count the start system

    # Mapping: (invTyeID, invTypeName, foreign_ask, local_bid, markup, invTyeID)
    markup = import_markup(station_id, 0, system_id, 0)

    # Get last week for history query
    last_week = pytz.utc.localize(
        datetime.datetime.utcnow() - datetime.timedelta(days=7))
    data = []

    for point in markup:
        # Add new values to dict and if there's a weekly volume append it to list
        new_values = {
            # Get local weekly volume for that item
            'weekly_volume': OrderHistory.objects.filter(mapregion_id=station.region.id,
                                                                 invtype_id=point['id'],
                                                                 date__gte=last_week)
            .aggregate(Sum("quantity"))['quantity__sum'],

            # Get filtered local bid qty
            'bid_qty_filtered': Orders.active.filter(stastation_id=station_id,
                                                      invtype_id=point['id'], is_bid=True,
                                                      minimum_volume=1,
                                                      price__gte=(point['local_bid'] - (point['local_bid'] * 0.01)))
            .aggregate(Sum("volume_remaining"))['volume_remaining__sum'],

            # Get filtered ask qty of the other system
            'ask_qty_filtered': Orders.active.filter(mapsolarsystem_id=system_id,
                                                      invtype_id=point['id'], is_bid=False,
                                                      minimum_volume=1,
                                                      price__lte=(point['foreign_ask'] + (point['foreign_ask'] * 0.01)))
            .aggregate(Sum("volume_remaining"))['volume_remaining__sum']}
        point.update(new_values)

        # Calculate potential profit ((local_bid - foreign_ask) * weekly_volume)
        if point['weekly_volume'] is not None:
            point['potential_profit'] = ((point['local_bid'] - point['foreign_ask']) * point['weekly_volume'])
            data.append(point)

    data.sort(key=itemgetter('potential_profit'), reverse=True)

    rcontext = RequestContext(request, {'system': system, 'markup':
                              data, 'path': path, 'jumps': numjumps})

    return render_to_response('station/_import_system.haml', rcontext)


def import_region(request, station_id=60003760, region_id=10000002):

    """
    Generates a list like http://goonmetrics.com/importing/
    Pattern: Region -> Station
    """

    # Get region, station and markup
    region = MapRegion.objects.get(id=region_id)
    station = StaStation.objects.get(id=station_id)
    markup = import_markup(station_id, region_id, 0, 0)

    # Get last week for history query
    last_week = pytz.utc.localize(
        datetime.datetime.utcnow() - datetime.timedelta(days=7))

    data = []

    for point in markup:
    # Add new values to dict and if there's a weekly volume append it to list
        new_values = {
            # Get local weekly volume for that item
            'weekly_volume': OrderHistory.objects.filter(mapregion_id=station.region.id,
                                                         invtype_id=point['id'],
                                                         date__gte=last_week)
            .aggregate(Sum("quantity"))['quantity__sum'],

            # Get filtered local bid qty
            'bid_qty_filtered': Orders.active.filter(stastation_id=station_id,
                                                      invtype_id=point['id'], is_bid=True,
                                                      minimum_volume=1,
                                                      price__gte=(point['local_bid'] - (point['local_bid'] * 0.01)))
            .aggregate(Sum("volume_remaining"))['volume_remaining__sum'],

            # Get filtered ask qty of the other region
            'ask_qty_filtered': Orders.active.filter(mapregion_id=region_id,
                                                      invtype_id=point['id'], is_bid=False,
                                                      minimum_volume=1,
                                                      price__lte=(point['foreign_ask'] + (point['foreign_ask'] * 0.01)))
            .aggregate(Sum("volume_remaining"))['volume_remaining__sum']}
        point.update(new_values)

        # Calculate potential profit ((foreign_ask - local_bid) * weekly_volume)
        if point['weekly_volume'] is not None:
            point['potential_profit'] = ((point['local_bid'] - point['foreign_ask']) * point['weekly_volume'])
            data.append(point)

    data.sort(key=itemgetter('potential_profit'), reverse=True)

    rcontext = RequestContext(request, {'region': region, 'markup': data})

    return render_to_response('station/_import_region.haml', rcontext)
