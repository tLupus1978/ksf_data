# KSF data fetcher
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

This component adds support for [KSF substitutions] to Home Assistant:

If you like this component, please give it a star on [github](https://github.com/tLupus1978/ksf_data).

## Installation

1. Ensure that [HACS](https://hacs.xyz) is installed.
2. Install **ksf_data** integration via HACS.
3. Add configuration section in home assistant configuration
4. You'll need to restart Home Assistant now!

In case you would like to install manually:

1. Copy the folder `custom_components/ksf_data` to `custom_components` in your Home Assistant `config` folder.
2. Add configuration section in home assistant configuration

## Configuration
The plugin can not be configured via the UI, so you'll need to write some YAML.
You'll need to add instances of the ```sensor``` integration with the ksf_data - see below
It is recommended, to use [Home Assistans feature for storing secrets](https://www.home-assistant.io/docs/configuration/secrets/), in order to not directly include them in your configuration.yaml.

```yaml
sensor:
    - platform: ksf_data
      name:  Usable name
      username: <schulportal login name>
      password: <schulportal password>
    - platform: ksf_data
      name:  Heinz Müller
      username: heinz.mueller
      password: 12012006
    ...
```

## What it does
A very simple Home Assistant custom component to query the schulportal.hessen.de for Kopernikusschule Freigericht (KSF).
As the schulportal page changes sometimes, it could be that there are changes required for fetching the data from the page.

Sadly, the LANIS API (https://github.com/kurwjan/LanisAPI) is not working for the KSF, therefore this component is based on an own implementation.

See sensor.py - the component fetches the data every 10 minutes from the schulportal page.

## Usage in Home Assistant UI
You can use this to get the data in a good strucutre (markdown card!)

```yaml
{% set data = state_attr('sensor.ksf_daten_heinz_mueller', 'SubstitutePlan')|from_json %}
{% for i in range(0, data | count ) %}
### {{ data[i]['date'] }}
{% for s in range(0, data[i]['substitutions'] | count ) %}
{% if data[i]['substitutions'][s]['hours'] == "" %}
{{ data[i]['substitutions'][s]['notice'] }}
{% else %}
{{ data[i]['substitutions'][s]['hours'] }} {% if data[i]['substitutions'][s]['subject_old'] != "" %} - {{ data[i]['substitutions'][s]['subject_old'] }} {% endif %} - statt {{ data[i]['substitutions'][s]['teacher'] }} {% if data[i]['substitutions'][s]['substitute'] != "" %} jetzt {{ data[i]['substitutions'][s]['substitute'] }} {% endif %} {% if data[i]['substitutions'][s]['room'] != "" %} in {{ data[i]['substitutions'][s]['room'] }} {% endif %} {% if data[i]['substitutions'][s]['notice'] != None %} - {{ data[i]['substitutions'][s]['notice'] }} {% endif %}
{% endif %}
{% endfor %}
{% endfor %}
```
see e.g.: 
![Lovelace UI of markdown card](ksf_data_lovelace_example.jpg)
