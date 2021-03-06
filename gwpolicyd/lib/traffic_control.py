import os
import socket
import struct
from datetime import datetime
import time

# Django models
from web.policy.models import Policy, PolicyJob, TrafficControlClass
from django.db import transaction

TC = '/sbin/tc'
HASH_TABLE_START = 0x100
REFRESH_INTERVAL = 5

class AddressFamily:
  """
  Possible address families.
  """
  Ethernet = 1
  IPv4 = 4
  IPv6 = 6

class PolicyControl(object):
  """
  Policy control (an interface to tc).
  """
  interface = None

  # Level 2 hash tables
  tables = None
  next_table_id = HASH_TABLE_START
  l1_tables = None

  # Filter rules
  filters = None

  def __init__(self, interface, prefix, debug = False):
    """
    Class constructor.
    
    @param interface: Interface on which to operate
    @param prefix: IPv4 subnet prefix
    @param debug: Should debugging be enabled
    """
    self.interface = interface
    self.prefix = prefix
    self.debug = debug
    self.tables = {}
    self.l1_tables = {}
    self.filters = {}

    for x, family in AddressFamily.__dict__.iteritems():
      if not x.startswith('__'):
        self.tables[family] = {}

    # Create initial rules
    self.create_initial()

  def tc(self, command):
    """
    Executes a traffic control command.
    """
    if self.debug:
      print "tc %s" % command

    os.system('%s %s' % (TC, command))
  
  def remove_all_rules(self):
    """
    Removes all set stuff.
    """
    self.tc('qdisc del dev %s root handle 1: htb default 0' % self.interface)

  def get_hash_table_id(self):
    """
    Returns the next available hash table id and marks it as
    used.
    """
    hid = self.next_table_id
    self.next_table_id += 1
    return hid

  def create_initial(self):
    """
    Creates the initial rules.
    """
    # Initialize qdisc
    self.tc('qdisc add dev %s root handle 1: htb default 0' % self.interface)

    # -- Ethernet
    # Initialize L1 hash table
    l1_id = self.get_hash_table_id()
    self.tc('filter add dev %s parent 1: prio 1 handle %x: protocol ip u32 divisor 256' % (self.interface, l1_id))

    # L1 hash table lookup (MAC) - destination MAC lives at offset -14
    self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht 800:: ' \
            'match u8 0x00 0x00 ' \
            'hashkey mask 0x0000ff00 at -12 ' \
            'link %x:' % (self.interface, l1_id))
    self.l1_tables[AddressFamily.Ethernet] = l1_id

    # -- IPv4
    # Initialize L1 hash table
    l1_id = self.get_hash_table_id()
    self.tc('filter add dev %s parent 1: prio 1 handle %x: protocol ip u32 divisor 256' % (self.interface, l1_id))

    # L1 hash table lookup (IPv4) - destination address lives at offset 16
    self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht 800:: ' \
            'match ip dst %s.0.0/16 ' \
            'hashkey mask 0x0000ff00 at 16 ' \
            'link %x:' % (self.interface, self.prefix, l1_id))
    self.l1_tables[AddressFamily.IPv4] = l1_id

  def get_hash_keys(self, family, addr):
    """
    Computes the hash keys.

    @param family: Address family (4 for IPv4)
    @param addr: Address
    @return: A tuple of L1 and L2 hash keys
    """
    if family == AddressFamily.Ethernet:
      mac = addr.split(':')
      return int(mac[4], 16), int(mac[5], 16)
    elif family == AddressFamily.IPv4:
      raw = socket.inet_pton(socket.AF_INET, addr)
      return ord(raw[2]), ord(raw[3])
    elif family == AddressFamily.IPv6:
      raise NotImplementedError
  
  def create_hash_table(self, family, l1, l2):
    """
    Creates a new level 2 hash table for filter lookups.
    
    @param family: Address family
    @param l1: L1 hash key
    @param l2: L2 hash key
    """
    if family == AddressFamily.Ethernet:
      # Initialize L2 hash table
      l2_id = self.get_hash_table_id()
      self.tc('filter add dev %s parent 1: prio 1 handle %x: protocol ip u32 divisor 256' % (self.interface, l2_id))

      # L2 hash table lookup (MAC)
      self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht %x:%x: ' \
              'match u8 0x%x 0xFF at -10 ' \
              'hashkey mask 0x000000ff at -12 ' \
              'link %x:' % (self.interface, self.l1_tables[family], l1, l1, l2_id))
    elif family == AddressFamily.IPv4:
      # Initialize L2 hash table
      l2_id = self.get_hash_table_id()
      self.tc('filter add dev %s parent 1: prio 1 handle %x: protocol ip u32 divisor 256' % (self.interface, l2_id))
      
      # L2 hash table lookup (IPv4)
      self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht %x:%x: ' \
              'match ip dst %s.%d.0/24 ' \
              'hashkey mask 0x000000ff at 16 ' \
              'link %x:' % (self.interface, self.l1_tables[family], l1, self.prefix, l1, l2_id))
    else:
      return

    # Register hash table
    self.tables[family][l1] = l2_id

  def insert_filter(self, family, addr, class_id):
    """
    Inserts a filter.

    @param family: Address family
    @param addr: Destination address
    @param class_id: Numeric class identifier
    """
    # Generate hash keys and create L2 table if one does not exist
    l1, l2 = self.get_hash_keys(family, addr)
    if l1 not in self.tables[family]:
      self.create_hash_table(family, l1, l2)
    
    # Fetch L2 hash table identifier and priority
    l2_id = self.tables[family][l1]

    # Create filter
    if family == AddressFamily.Ethernet:
      mac = [int(x, 16) for x in addr.split(':')]
      self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht %x:%x: ' \
              'match u16 0x%02x%02x 0xffff at -14 ' \
              'match u32 0x%02x%02x%02x%02x 0xffffffff at -12 ' \
              'flowid 1:%x' \
              % (
                  self.interface, l2_id, l2,
                  mac[0], mac[1], mac[2], mac[3],
                  mac[4], mac[5],
                  class_id
                ))
    elif family == AddressFamily.IPv4:
      self.tc('filter add dev %s parent 1: prio 1 protocol ip u32 ht %x:%x: ' \
              'match ip dst %s/32 ' \
              'flowid 1:%x' % (self.interface, l2_id, l2, addr, class_id))
    elif family == AddressFamily.IPv6:
      pass

    self.filters[family, addr] = class_id
  
  def update_filter(self, family, addr, class_id):
    """
    Updates an existing filter to point to a new class.

    @param family: Address family
    @param addr: Destination address
    @param class_id: Numeric class identifier
    """
    if (family, addr) not in self.filters:
      return self.insert_filter(family, addr, class_id)
    
    # Check if there are actually no changes
    if self.filters[family, addr] == class_id:
      return

    # Get hash keys so we know which filter to update
    l1, l2 = self.get_hash_keys(family, addr)
    l2_id = self.tables[family][l1]

    # Change filter
    self.tc('filter change dev %s parent 1: protocol ip prio 1 ' \
            'handle %x:%x:800 u32 flowid 1:%x' \
            % (self.interface, l2_id, l2, class_id))

    self.filters[family, addr] = class_id
  
  def remove_filter(self, family, addr):
    """
    Removes an existing filter.

    @param family: Address family
    @param addr: Destination address
    """
    if (family, addr) not in self.filters:
      return

    # Get hash keys so we know which filter to remove
    l1, l2 = self.get_hash_keys(family, addr)
    l2_id = self.tables[family][l1]

    # Remove filter
    self.tc('filter del dev %s parent 1: protocol ip prio 1 ' \
            'handle %x:%x:800 u32' \
            % (self.interface, l2_id, l2))

    del self.filters[family, addr]

  def insert_class(self, class_id, bandwidth):
    """
    Inserts a traffic control class.

    @param class_id: Numeric class identifier
    @parma bandwidth: Bandwidth limit in kbit/s
    """
    self.tc('class add dev %s parent 1: classid 1:%x htb rate %dkbit ceil %dkbit' \
            % (self.interface, class_id, bandwidth, bandwidth))

class Controller(object):
  """
  A class that uses PolicyControl to modify policy accoording to
  information from the database.
  """
  def __init__(self, interface, prefix, refresh, debug = False):
    """
    Class constructor.
    
    @param interface: Interface on which to operate
    @param prefix: IPv4 subnet prefix
    @param refresh: Policy poll interval
    @param debug: Should debugging be enabled
    """
    self.policy = PolicyControl(interface, prefix, debug)
    self.interface = interface
    self.prefix = prefix
    self.refresh = refresh
    self.debug = debug

  @transaction.commit_manually
  def check_jobs(self):
    """
    Checks if any jobs need to be executed.
    """
    # Check for any explicit jobs
    for job in PolicyJob.objects.all():
      try:
        policy = Policy.objects.get(node = job.node, addr = job.addr)
        self.policy.update_filter(policy.family, policy.addr, policy.tc_class.id)
      except Policy.DoesNotExist:
        self.policy.remove_filter(job.family, job.addr)

      job.delete()

    transaction.commit()

  def init_policy(self):
    """
    Initializes policy.
    """
    # Register traffic control classes
    for c in TrafficControlClass.objects.all():
      self.policy.insert_class(c.id, c.bandwidth)
    
    # Load all existing rules
    for policy in Policy.objects.all():
      self.policy.insert_filter(policy.family, policy.addr, policy.tc_class.id)

  def check_interface(self):
    """
    Checks if interface is still available and resets the whole thing
    if it disappears.
    """
    if os.system('/sbin/ip link sh dev %s 2>/dev/null >/dev/null' % self.policy.interface) != 0:
      # Interface has disappeared
      print "WARNING: Interface %s has disappeared. Waiting for it to come back..."

      # Check interface every 30 seconds
      while True:
        time.sleep(30)
        if os.system('/sbin/ip link sh dev %s 2>/dev/null >/dev/null' % self.policy.interface) == 0:
          break

      # Interface is back we need to reset everything
      print "WARNING: Interface %s has reappeared. Restarting..."
      self.policy = PolicyControl(self.interface, self.prefix, self.debug)
      self.init_policy()

  def run(self):
    """
    A loop that monitors for changes and updates the traffic policy.
    """
    self.init_policy()
    last_interface_check = time.time()
   
    while True:
      try:
        time.sleep(REFRESH_INTERVAL)
        self.check_jobs()
        
        if time.time() - last_interface_check > 600:
          self.check_interface()
          last_interface_check = time.time()
      except KeyboardInterrupt:
        raise
      except:
        pass
  
  def shutdown(self):
    """
    Shuts down this controller.
    """
    self.policy.remove_all_rules()

