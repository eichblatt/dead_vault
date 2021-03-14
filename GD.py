import requests
import json
import os
import pdb
import datetime,time,math
from importlib import reload
from operator import attrgetter,methodcaller

class GDArchive:
  """ The Grateful Dead Collection on Archive.org """
  def __init__(self,dbpath,url='https://archive.org',reload_ids=False,load_meta=False):
    self.url = url
    self.dbpath = dbpath
    self.idpath = os.path.join(self.dbpath,'ids.json')
    
    self.url_scrape = self.url + '/services/search/v1/scrape'
    self.scrape_parms = {'debug':'false','xvar':'production','total_only':'false','count':'10000','sorts':'date asc,avg_rating desc,num_favorites desc,downloads desc','fields':'identifier,date,avg_rating,num_reviews,num_favorites,stars,downloads,files_count,format,collection,source,subject,type'}
    self.tapes = self.load_tapes(reload_ids)
    self.tape_dates = self.get_tape_dates()
    self.dates = sorted(self.tape_dates.keys())
    self.meta_loaded = False
    if load_meta: self.load_metadata()

  def __str__(self):
    return self.__repr__()

  def __repr__(self):
    retstr = F"Grateful Dead Archive with {len(self.tapes)} tapes on {len(self.dates)} dates from {self.dates[0]} to {self.dates[-1]} "
    if self.meta_loaded: retstr += F"with track-level metadata. "
    return retstr
  
  def load_metadata(self):
    for d in self.dates:
       self.tape_dates[d][0].get_metadata()
    self.meta_loaded = True

  def best_tape(self,date):
    if not date in self.dates: 
      print ("No Tape for date {}".format(date))
      return None
    return self.tape_dates[date][0]
     
  def get_tape_dates(self):
    tape_dates = {}
    for tape in self.tapes:
      k = tape.date
      if not k in tape_dates.keys():
        tape_dates[k] = [tape]
      else:
        tape_dates[k].append(tape)
    # Now that we have all tape for a date, put them in the right order
    self.tape_dates = {}
    for k,v in tape_dates.items():
      self.tape_dates[k] = sorted(v,key=methodcaller('compute_score'),reverse=True) 
    return self.tape_dates

  def write_tapes(self,tapes):
    os.makedirs(os.path.dirname(self.idpath),exist_ok=True)
    json.dump(tapes,open(self.idpath,'w'))

  def load_tapes(self,reload_ids=False):
    if (not reload_ids) and os.path.exists(self.idpath):
      tapes = json.load(open(self.idpath,'r'))
    else:
      tapes = []
      for year in range(1965,1996,1):
        tapes.extend(self.get_tapes(year))
      self.write_tapes(tapes)
    return [GDTape(self.dbpath,tape) for tape in tapes]

  def get_tapes(self,year):
    current_rows = 0
    tapes = []
    r = self.get_chunk(year)
    j = r.json()
    total = j['total']
    print ("total rows {}".format(total))
    current_rows += j['count']
    tapes=j['items']
    while current_rows < total:  
      cursor = j['cursor']
      r = self.get_chunk(year,cursor)
      j = r.json()
      cursor = j['cursor']
      current_rows += j['count']
      tapes.extend(j['items'])
    return tapes

  def get_chunk(self,year,cursor=None):
    parms = self.scrape_parms.copy()
    if cursor!=None: parms['cursor'] = cursor
    query = 'collection:GratefulDead AND year:'+str(year)
    parms['q'] = query
    r = requests.get(self.url_scrape,params=parms)
    print("url is {}".format(r.url))
    if r.status_code != 200: print ("error collecting data"); raise Exception('Download','Error {} collection'.format(r.status_code))
    return r

class GDTape:
  """ A Grateful Dead Identifier Item -- does not contain tracks """
  def __init__(self,dbpath,raw_json):
    self.dbpath = dbpath
    self._playable_formats = ['Ogg Vorbis','VBR MP3','Shorten','Flac','MP3']
    attribs = ['date','identifier','avg_rating','format','collection','num_reviews','downloads']
    for k,v in raw_json.items():
       if k in attribs: setattr(self,k,v)
    self.url_metadata = 'https://archive.org/metadata/'+self.identifier
    self.url_details = 'https://archive.org/details/'+self.identifier
    self.date = str((datetime.datetime.strptime(raw_json['date'] ,'%Y-%m-%dT%H:%M:%SZ')).date()) 
    if 'avg_rating' in raw_json.keys(): self.avg_rating = float(self.avg_rating)
    else: self.avg_rating = 2.0

  def __str__(self):
    return self.__repr__()

  def __repr__(self):
    tag = "SBD" if self.stream_only() else "aud"
    retstr = '{} - {} - {:5.2f} - {}\n'.format(self.date,tag,self.avg_rating,self.identifier)
    return retstr

  def stream_only(self):
    return 'stream_only' in self.collection 

  def compute_score(self):
    """ compute a score for sorting the tape. High score means it should be played first """    
    score = 0
    if self.stream_only(): score = score + 1000
    score = score + math.log(1+self.downloads)
    score = score + self.avg_rating * 10
    return score

  def contains_sound(self):
    return len(list(set(self._playable_formats) & set(self.format)))>0

  def get_metadata(self):
    self.tracks = []
    date = datetime.datetime.strptime(self.date,'%Y-%m-%d').date() 
    meta_path = os.path.join(self.dbpath,str(date.year),str(date.month),self.identifier+'.json')
    if os.path.exists(meta_path): 
      page_meta = json.load(open(meta_path,'r'))
    else:
      r = requests.get(self.url_metadata)
      print("url is {}".format(r.url))
      if r.status_code != 200: print ("error pulling data for {}".format(self.identifier)); raise Exception('Download','Error {} url {}'.format(r.status_code,self.url_metadata))
      try:
        page_meta = r.json()
      except ValueError:
        print ("Json Error {}".format(r.url))
        return None
      except:
        print ("Json Error, probably")
        return None

    # self.reviews = page_meta['reviews'] if 'reviews' in page_meta.keys() else []
    for ifile in page_meta['files']:
       try:
         if ifile['format'] in self._playable_formats:
           self.append_track(ifile)
       except KeyError: pass
       except Exception as e:   # TODO handle this!!!
         raise (e)
    os.makedirs(os.path.dirname(meta_path),exist_ok=True)
    json.dump(page_meta,open(meta_path,'w'))
    #return page_meta
    return self.tracks

  def append_track(self,tdict):
    source = tdict['source']
    if source == 'original':
      orig = tdict['name']
    else:
      orig = tdict['original']
    trackindex = None
    for i,t in enumerate(self.tracks):
      if orig == t.original:  # add in alternate formats
        trackindex = i
        # make sure that this isn't a duplicate!!!
        t.add_file(tdict)
        return t
    self.tracks.append(GDTrack(tdict,self.identifier))

class GDTrack:
  """ A track from a GDTape recording """
  def __init__(self,tdict,parent_id):
    self.parent_id = parent_id
    attribs = ['track','original','title']
    for k,v in tdict.items():
       if k in attribs: setattr(self,k,v)
    # if these don't exist, i'll throw an error!
    if tdict['source'] == 'original': self.original = tdict['name']
    try:
      self.track = int(self.track) if 'track' in dir(self) else None
    except ValueError:
      self.track = None 
    self.files = []
    self.add_file(tdict)

  def __str__(self):
    return self.__repr__()

  def __repr__(self):
    retstr = 'track {}. {}'.format(self.track,self.title)
    return retstr
      
  def add_file(self,tdict):
    attribs = ['name','format','size','source']
    d = {k:v for (k,v) in tdict.items() if k in attribs}
    d['size'] = int(d['size'])
    d['url'] = 'https://archive.org/download/'+self.parent_id+'/'+d['name']
    self.files.append(d)
  # method to play(), pause(). 


