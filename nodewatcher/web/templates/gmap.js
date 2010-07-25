<script src="http://maps.google.com/maps?file=api&amp;v=2&amp;key={{ google_key|escape }}" type="text/javascript"></script>
<script src="{{ MEDIA_URL }}js/gmap.js" type="text/javascript"></script>
<script type="text/javascript">
/* <![CDATA[ */
  function createMap() {
    if (google.maps.BrowserIsCompatible()) {
      var map = new google.maps.Map2(document.getElementById("gmap"));
      map.setCenter(new google.maps.LatLng({{ lat }}, {{ long }}), {{ zoom }});
      map.removeMapType(map.getMapTypes()[1]);
      map.enableDoubleClickZoom();
      map.addControl(new google.maps.SmallMapControl());
      map.addControl(new google.maps.MapTypeControl());
      map.addControl(new google.maps.ScaleControl());
      
      {% if not full %}
      var m = null;
      {% if marker_lat and marker_long %}
      m = new google.maps.Marker(new google.maps.LatLng({{ marker_lat }}, {{ marker_long }}), {'icon': createIcon('{{ status|escapejs }}')});
      map.addOverlay(m);
      map.setCenter(m.getLatLng(), {{ node_zoom }});
      {% endif %}

      {% if clickable %}
      google.maps.Event.addListener(map, "click", function(overlay, p) {
        if (!overlay) {
          if (!m) {
            m = new google.maps.Marker(p, {'icon': createIcon('new'), 'clickable': false, 'draggable': true});
            google.maps.Event.addListener(m, "dragend", function(p) {
              document.getElementById("id_geo_lat").value = p.lat();
              document.getElementById("id_geo_long").value = p.lng();
            });
            map.addOverlay(m);
          }
          else {
            m.setLatLng(p);
          }

          document.getElementById("id_geo_lat").value = p.lat();
          document.getElementById("id_geo_long").value = p.lng();
        }
      });
      {% endif %}
      {% endif %}
      
      {% if callback %}
      if (typeof {{ callback }} == "function") {
        {{ callback }}(map);
      }
      {% endif %}
    }
  }

  $(document).ready(function() { createMap(); });
/* ]]> */
</script>
