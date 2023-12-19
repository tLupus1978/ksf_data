# KSF data fetcher

## What it does
A very simple Home Assistant custom component to query the hesse


## What you'll need

## Installation
**You'll need to restart Home Assistant now!**

The plugin can not be configured via the UI, so you'll need to write some YAML.
You'll need to add instances of the ```sensor``` integration with the platform ...

It is recommended, to use [Home Assistans feature for storing secrets](https://www.home-assistant.io/docs/configuration/secrets/), in order to not directly include them in your configuration.yaml.

```yaml
sensor:
    - platform: portainer
      url: http://<hostname, fqdn or ip>:9000
      name:  nas15
      username: !secret port_user
      password: !secret port_pass
# To monitor multiple docker hosts, you can add more instances as you need:
    - platform: portainer
      url: http://<hostname, fqdn or ip>:8080 # If you chose to open port 9000 as port 8080, for example
      name: pi10
      username: !secret port_user # If you have multiple instances with different credentials, make sure to create individual secret variables!
      password: !secret port_pass
```

## Why and how it's made

This component was created by GPT-4 over 3 2-hour sessions.

