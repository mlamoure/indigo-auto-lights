Auto Lights is a lighting automation plugin for the Indigo Home Automation system.

# What does it do?

Auto Lights is an **opinionated** lighting behavior template for your home. It enables you to set up Lighting Zones (
this is intentionally vague, you can define a Zone to be whatever you want), and configure behavior for each Zone that
standardizes the way Indigo controls lights in your home.

I originally built Auto Lights for my own use in a sensor-rich home, where nearly every room is managed by Auto Lights.
However, Auto Lights can be used in less complex homes as well. The idea is to save you from configuring many many
Indigo Triggers and Variables to achieve a basic level of automatic light control functionality to do things like:

* Turn on lights automatically, based on presence.
* Setup Lighting Periods (times of the day), which define based on the time of day whether Auto Lights is the primary
  for turning lights on and off, or just off, or nothing at all, for that period.
* Turn off lights when presence is not detected

Auto Lights simplifies your setup by providing a streamlined template, letting you focus on fine-tuning your triggers
instead of handling routine configurations. More advanced features include:

* When it's detected that someone changed the lighting state for a Zone, Auto Lights places that Zone in
  a [lock](#locks), so that it will not override the change from the user. Locks are time-based, and can be extended
  based on persistent presence until the room is empty again.
* Optionally, a luminance device can be defined, with a minimum luminance setting. So the logic becomes: If Presence
  while Dark and Period is set to Auto Lights Control -> Turn on the lights.
* For dimmer devices, Auto Lights can optionally set the brightness to a % based on the current luminance level of the
  room. For example: target brightness = (1 - (Current Luminance / Minimum Luminance)) * 100

# Requirements

- [x] Latest Indigo - I only test on the latest
- [x] "Allow Remote Access" must be on for your server, with Reflector and API Key -- See [here](#the-web-config) for
  why.
- [x] Presence and lighting devices to control, for any Zone you wish to use with Auto Lights

## The Web Config

Auto Lights uses a web interface to build and configure your Zones. This path was chosen because the interface needed is
too advanced for the Indigo native ConfigUI.

The Web Config is run as a separate web server on your Indigo Server. Because of this, it must interact with your Indigo
via API, and I've only implemented support for using the API key. API keys are only enabled for Indigo with support for
the reflector. While technically you do not need to use the reflector and can point to http://localhost:8186, you must
enable reflector to set api keys via the indigo site. I recommend creating a unique API key for Auto
Lights [here](https://www.indigodomo.com/account/authorizations).

There is no authorization on the Web Config interface itself. If this concerns you, there are two options available:

* Set your web server to only bind to localhost
* Disable the web config server once you've configured your Auto Lights. The plugin does not need it for execution, it's
  only needed to build your config.

# Documentation

See documentation [here](Auto Lights.indigoPlugin/Contents/Server Plugin/config_web_editor/static/README.MD)