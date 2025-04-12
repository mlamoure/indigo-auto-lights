Auto Lights is a lighting automation plugin for the Indigo Home Automation system.

# What does it do?

Auto Lights is an opinionated lighting behavior template for your house. It enables you to set up Lighting Zones, and
configure behavior for each Zone that standardizes the way Indigo controls lights in your home.

I originally built Auto Lights for my own use in a sensor-rich home, where nearly every room is managed by it.
However, Auto Lights can be tailored for homes with fewer sensors. Without it, configuring lights using Indigo Triggers
and Variables can be very labor-intensive. Auto Lights simplifies your setup by providing a streamlined template,
letting you focus on fine-tuning your triggers instead of handling routine configurations.

Main features of Auto Lights:

* Each Zone has a set of "On / Off Lights", and a set of [presence devices](#presence-devices).
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

# Presence Devices

> **TIP:** Auto Lights supports the use of the Timed Device plugin. It can be extremely helpful for smoothing out intermittent signals or combining multiple inputs into a unified virtual presence device. For example, in a Living Room that may lack a dedicated motion sensor, you can create a threshold timer that merges the state of your motion sensor with signals from an IP-enabled TV to detect activity.

# Lighting Periods

# Locks

# Todo

Originally built as a script before becoming a plugin in 2025, Auto Lights has been rigorously tested, though the conversion
may have introduced issues. The following improvements are planned:

- [ ] Make luminance devices and minimum luminance levels optional
- [ ] Add validation to the forms for required items
- [ ] Remove any on/off light from the list of off lights
- [ ] Enhance documentation and tool tips
- [ ] Test locking functionality and lock resets
- [ ] Improve formatting of info.log() in the Indigo event log
- [ ] Support special rules for a Zone or a Lighting Period
- [ ] Clarify plugin setup for using a reflector versus a local address for the Indigo web server

