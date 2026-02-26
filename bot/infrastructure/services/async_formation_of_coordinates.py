
async def get_point(place):
    try:
        coordinates_arr = str(place.Point.coordinates).split(',')
        latitude  = coordinates_arr[1].replace(' ', '').replace('\n', '')
        longitude = coordinates_arr[0].replace(' ', '').replace('\n', '')
        return {'result': True,'latitude': latitude, 'longitude': longitude}
    except:
        return {'result': False,'latitude': '', 'longitude': ''}
