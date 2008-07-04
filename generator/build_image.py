#!/usr/bin/python
#
# Lj-Wifi OpenWRT image builder
#
# Copyright (C) 2008 Jernej Kos <kostko@unimatrix-one.org>
#
from config_generator import OpenWrtConfig
from optparse import OptionParser
import os
import sys

print "============================================================================"
print "                   Ljubljana WiFi Mesh Image Generator"
print "============================================================================"

parser = OptionParser()
parser.add_option('--arch', dest = 'arch', default = 'mipsel',
                  help = 'Hardware architecture (eg. mipsel)')
parser.add_option('--iface', dest = 'iface',
                  help = 'Wireless interface name (eg. "wl0")')
parser.add_option('--driver', dest = 'driver',
                  help = 'Wireless driver name (eg. "broadcom")')
parser.add_option('--port-layout', dest = 'layout', default = 'wrt54gl',
                  help = 'Port layout (valid layouts: "wrt54gl", "wrt54gs")')
parser.add_option('--node-type', dest = 'type', default = 'adhoc',
                  help = 'Node type (valid types: "adhoc", "ap")')
parser.add_option('--password', dest = 'password',
                  help = 'Wanted root password')
parser.add_option('--hostname', dest = 'hostname',
                  help = 'Node hostname')
parser.add_option('--ip', dest = 'ip',
                  help = 'Node main IP address')
parser.add_option('--add-subnet', action = 'append', dest = 'subnets',
                  help = 'Adds a subnet (eg. "wl0,10.16.200.32/28,dchp,olsr" for subnets that should '
                         'be announced via DHCP and OLSR)')
parser.add_option('--add-iface', action = 'append', dest = 'interfaces',
                  help = 'Adds an interface (eg. "wan,eth0.1,dhcp,init" for DHCP assigned addresses '
                         'or "wan,eth0.1,192.168.0.12/24,192.168.0.1,init" for static configuration)')
parser.add_option('--captive-portal', action = 'store_true', dest = 'captive_portal',
                  help = 'Enables the nodogsplash captive portal.')
parser.add_option('--vpn', action = 'store_true', dest = 'vpn',
                  help = 'Enables the VPN tunnel.')
parser.add_option('--vpn-username', dest = 'vpn_username',
                  help = 'Specifies the assigned VPN username.')
parser.add_option('--vpn-password', dest = 'vpn_password',
                  help = 'Specifies the assigned VPN password.')
parser.add_option('--vpn-keyfile', dest = 'vpn_keyfile',
                  help = 'Specifies the assigned VPN keyfile.')

(options, args) = parser.parse_args()
options = options.__dict__

# Cleanup stuff from previous builds
os.system("rm -rf files/*")
os.system("rm -rf imagebuilder/bin/*")
os.mkdir("files/etc")

x = OpenWrtConfig()

for key in ('iface', 'driver', 'password', 'hostname', 'ip'):
  if not options[key]:
    print "Error: You have to specify --interface, --driver, --password, --hostname and --ip!"
    exit()

x.setArch(options['arch'])
x.setWifiIface(options['iface'], options['driver'])
x.setPortLayout(options['layout'])
x.setNodeType(options['type'])
x.setPassword(options['password'])
x.setHostname(options['hostname'])
x.setIp(options['ip'])

print ">>> Configuring image with the following settings:"
print ""
print "  IP address: ", options['ip']
print "  Node type:  ", options['type']
print "  Hostname:   ", options['hostname']
print "  WiFi iface: ", options['iface']
print "  Driver:     ", options['driver']
print ""

# Add interfaces
if options['interfaces']:
  for iface in options['interfaces']:
    iface = iface.split(",")
    id, name = iface[0:2]

    if 'dhcp' in iface:
      ip, cidr = (None, 0)
      gw = None
    else:
      ip, cidr = iface[2].split("/")
      gw = iface[3]

    init = 'init' in iface
    olsr = 'olsr' in iface
    strict = 'strict' in iface

    x.addInterface(id, name, ip, int(cidr) or None, gw, init, olsr)
    print ">>> Added interface '%s/%s' (init = %s, olsr = %s)." % (id, name, init, olsr)

# Add subnets
if options['subnets']:
  for subnet in options['subnets']:
    subnet = subnet.split(',')
    iface = subnet[0]
    dhcp = 'dhcp' in subnet
    olsr = 'olsr' in subnet
    subnet, cidr = subnet[1].split("/")

    x.addSubnet(iface, subnet, int(cidr), dhcp, olsr)
    print ">>> Added subnet '%s/%s' to interface '%s'." % (subnet, cidr, iface)

# Enable captive portal
if options['captive_portal']:
  print ">>> Enabled captive portal."
  x.setCaptivePortal(True)

# Enable VPN and set VPN credentials
if options['vpn']:
  if not options['vpn_username'] or not options['vpn_password']:
    print "Error: VPN configuration requires username and password!"
    exit()
  
  if not x.hasInterface('wan'):
    print "Error: VPN configuration requires interface 'wan'!"

  x.setVpn(options['vpn_username'], options['vpn_password'])
  print ">>> Enabled VPN tunnel."

# Generates configuration and builds the image
print ">>> Generating image, please stand by..."
x.generate('files/etc')
x.build('imagebuilder')

