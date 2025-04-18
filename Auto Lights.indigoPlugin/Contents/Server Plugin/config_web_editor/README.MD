Auto Lights is a lighting automation plugin for the Indigo Home Automation system.

# What does it do?

Auto Lights is an opinionated lighting behavior template for your house. It enables you to set up Lighting Zones, and
configure behavior for each Zone that standardizes the way Indigo controls lights in your home.

I originally built Auto Lights for my own use in a sensor-rich home, where nearly every room is managed by it.
However, Auto Lights can be tailored for homes with fewer sensors. Without it, configuring lights using Indigo Triggers
and Variables can be very labor-intensive. Auto Lights simplifies your setup by providing a streamlined template,
letting you focus on fine-tuning your triggers instead of handling routine configurations.

Main features of Auto Lights:

* Each Zone has a set of "On / Off Lights", and a set of [presence devices](#zones-presence-devices).
* Each Zone has a set of Lighting Periods, which define based on the time of day whether Auto Lights is the primary for
  turning lights on and off, or just off, for that period.
* When presence is detected in a Zone, and the current Lighting Period indicates Auto Lights is in control of the
  lights, Auto Lights will turn on the lights in the On / Off Lights.
* When presence is not detected, and if there's an active period, Auto Lights will turn off the lights for that Zone.

More advanced features:

* When it's detected that someone changed the lighting state for a Zone, Auto Lights places that Zone in
  a [lock](#locks), so that
  it will not override the change from the user. Locks are time-based, and can be extended based on persistent presence
  until the room is empty again.
* Optionally, a luminance device can be defined, with a minimum luminance setting. So the logic becomes: If Presence
  while Dark -> Turn on the lights.
* For dimmer devices, Auto Lights can optionally set the brightness to a % based on the current luminance level of the
  room. For example: target brightness = (1 - (Current Luminance / Minimum Luminance)) * 100

# Requirements

- [x] Latest Indigo - I only test on the latest
- [x] "Allow Remote Access" must be on for your server, with Reflector and API Key -- See here for why.
- [x] Presence and lighting devices to control, for any Zone you wish to use with Auto Lights

## The Web Config

Auto Lights uses a web interface to build and configure your Zones. This path was chosen because the interface needed is
too advanced for the Indigo native ConfigUI.

The Web Config is run as a separate web server on your Indigo Server. Because of this, it must interact with your Indigo
via API, and I've only implemented support for using the API key, so therefore the reflector is required. I may look
into moving this to the native auth in the future.

There is no authorization on the Web Config interface itself. If this concerns you, there are two options available:

* Set your web server to only bind to localhost
* Disable the web config server once you've configured your Auto Lights. The plugin does not need it for execution, it's
  only needed to build your config.

# Plugin Settings

This section provides an overview of where you can configure the plugin within Indigo. It covers
general plugin options, how you might enable or disable certain features, and other high-level
choices for setup.

## Indigo Plugin Settings

In the Indigo Plugin Settings, you typically set up how the plugin interacts with Indigo’s internal
resources. The plugin may define references to Indigo variables or devices that it uses behind the
scenes. Usually, you won’t need to configure much manually here, but it’s good to review these
settings to ensure the plugin has the access and permissions it needs.

## Auto Lights Settings

Within Auto Lights Settings, you can fine-tune how the plugin behaves overall. For example, you
might control whether Auto Lights is globally enabled or assign a variable that determines guest
mode. These settings serve as a “master control” for features like lock durations or how the plugin
handles brightness calculations for all your Zones.

# ⏰💡 Lighting Periods 💡⏰

Lighting Periods let you define windows of time (like “Morning” or “Night”) that set different
behaviors for your lights. Each period has a start and end time, and a mode that describes what
should happen to the lights during that interval—such as turning them on, dimming them, or turning
them off altogether. If you ever notice a manual override (like a person flipping a switch),
Auto Lights respects it until any configured lock duration has passed.

# Zones

A Zone represents an area or room in your home where Auto Lights controls specific sets of lights
based on presence, time of day, and your configured lighting periods. By grouping devices into Zones,
you can easily manage them as a single unit—turning them on/off or adjusting brightness automatically
when someone enters or leaves a room. Zones also let Auto Lights lock out changes temporarily if you
manually adjust a light, so you keep control for as long as needed.

## Presence Devices {#zones-presence-devices}

> **TIP:** Auto Lights supports the use of the Timed Device plugin. It can be extremely helpful for smoothing out
> intermittent signals or combining multiple inputs into a unified virtual presence device. For example, in a Living
> Room
> that may lack a dedicated motion sensor, you can create a threshold timer that merges the state of your motion sensor
> with signals from an IP-enabled TV to detect activity.

## Locks {#zones-locks}

> **NOTE:** Locks do not persist plugin re-starts

* There are Indigo Actions to reset a lock for any given Zone, or all Zones.

# Todo

Originally built as a script before becoming a plugin in 2025, Auto Lights has been rigorously tested, though the
conversion
may have introduced issues. The following improvements are planned:

- [ ] Add validation to the forms for required items
- [ ] Enhance documentation and tool tips
- [ ] Improve formatting of info.log() in the Indigo event log
- [ ] Support special rules for a Zone or a Lighting Period
- [ ] Clarify plugin setup for using a reflector versus a local address for the Indigo web server
- [ ] Fix the web server shutdown

