# Template and context-related imports
from django.shortcuts import render_to_response
from django.http import HttpResponse
from django.template import RequestContext

# JSON for the live search
from django.utils import simplejson

# market_data models
from models import Orders

# eve_db models
from eve_db.models import InvType

"""
Those are our views. We have to use the RequestContext for CSRF protection, 
since we have a form (search) in every single of our views, as they extend 'base.haml'.
"""

def home(request):
		
		"""
		Returns our static home template with a CSRF protection for our search.
		"""
		
		# Create context for CSRF protection
		rcontext = RequestContext(request, {})
		
		return render_to_response('home.haml', rcontext)
		
def search(request):
	
		"""
		This adds a basic search view to element43.
		The names in the invTypes table are searched with a case insensitive LIKE query.
		"""
		
		# Get query from request
		query = request.POST.get('query', '')
		
		# Prepare list
		types = []
		
		# Only if the string is longer than 2 characters start looking in the DB
		if len(query) > 2:
			
				# Load published type objects matching the name
				types = InvType.objects.filter(name__icontains = query, is_published = True)
				
		# Create Context
		rcontext = RequestContext(request, {'types':types})		
		
		# Render template
		return render_to_response('search.haml', rcontext)
		
def live_search(request, query='a'):
	
		"""
		This adds a basic live search view to element43.
		The names in the invTypes table are searched with a case insensitive LIKE query and the result is returned as a JSON array of matching names.
		"""
		
		# Prepare lists
		types = []
		type_names = []
		
		# Default to empty array
		types_json = "[]"
		
		# Only if the string is longer than 2 characters start looking in the DB
		if len(query) > 2:
			
				# Load published type objects matching the name
				types = InvType.objects.filter(name__icontains = query, is_published = True)
				
				for single_type in types:
					type_names.append(single_type.name)
				
				# Turn names into JSON
				types_json = simplejson.dumps(type_names)
		
		# Return JSON without using any template
		return HttpResponse(types_json, mimetype = 'application/json')
		
def quicklook(request, type_id="34"):
		
		"""
		Generated a market overview for a certain type. Default to tritanium.
		"""
		
		type_object = InvType.objects.get(id = type_id)
		
		buy_orders = Orders.objects.filter(invtype = type_id, is_bid = True).order_by('-price')[:50]
		sell_orders = Orders.objects.filter(invtype = type_id, is_bid = False).order_by('price')[:50]

		rcontext = RequestContext(request, {'type':type_object, 'buy_orders':buy_orders, 'sell_orders':sell_orders})
		
		return render_to_response('quicklook.haml', rcontext)