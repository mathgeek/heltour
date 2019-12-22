import datetime
import responses
from django.test import TestCase
from unittest.mock import patch
from heltour.tournament import oauth
from .testutils import *


class LoginTestCase(TestCase):
    def setUp(self):
        createCommonLeagueData()

    def test_encode_decode_state(self, *args):
        # Just verify that encode/decode are symmetrical
        original_state = {'league': 'teamleague', 'token': None}
        encoded = oauth._encode_state(original_state)
        new_state = oauth._decode_state(encoded)
        self.assertEqual(original_state, new_state)

    @patch('heltour.tournament.oauth._encode_state', return_value='encodedstate')
    def test_oauth_redirect(self, *args):
        response = self.client.get(league_url('team', 'login'))
        expected_oauth_url = 'https://oauth.lichess.org/oauth/authorize' + \
                             '?response_type=code' + \
                             '&client_id=clientid' + \
                             '&redirect_uri=http://testserver/auth/lichess/' + \
                             '&scope=email:read%20challenge:read%20challenge:write' + \
                             '&state=encodedstate'
        self.assertRedirects(response, expected_oauth_url, fetch_redirect_response=False)
        oauth._encode_state.assert_called_with({'league': 'teamleague', 'token': None})


@patch('heltour.tournament.lichessapi.get_user_meta',
       return_value={'perfs': {'classical': {'rating': 2121, 'games': 10}}})
@patch('heltour.tournament.oauth._decode_state',
       return_value={'league': league_tag('team'), 'token': None})
@patch('django.utils.timezone.now',
       return_value=datetime.datetime(2019, 1, 1, 10, 30, 0, tzinfo=timezone.utc))
@responses.activate
class LoginWithCodeTestCase(TestCase):
    def setUp(self):
        createCommonLeagueData()

        responses.add(responses.POST, 'https://oauth.lichess.org/oauth',
                      json={'access_token': '1234',
                            'refresh_token': '4567',
                            'expires_in': 3600,
                            'token_type': 'bearer'})
        responses.add(responses.GET, 'https://lichess.org/api/account',
                      json={'username': 'testuser'})
        responses.add(responses.GET, 'https://lichess.org/api/email',
                      json={'email': 'testuser@example.com'})

        self.auth_params = {'code': 'abc', 'state': 'encodedstate'}

    def test_new_user(self, *args):
        response = self.client.get(reverse('lichess_auth'), self.auth_params, follow=True)

        self.assertRedirects(response, league_url('team', 'user_dashboard'))
        self.assertContains(response, '<h3>testuser</h3>', status_code=200)
        oauth._decode_state.assert_called_with('encodedstate')

        player = Player.objects.get(lichess_username='testuser')

        self.assertEqual(2121, player.rating_for(get_league('team')))
        self.assertEqual(10, player.games_played_for(get_league('team')))

        self.assertEqual('1234', player.oauth_token.access_token)
        self.assertEqual('4567', player.oauth_token.refresh_token)
        self.assertEqual(datetime.datetime(2019, 1, 1, 11, 30, 0, tzinfo=timezone.utc),
                         player.oauth_token.expires)
        self.assertEqual('bearer', player.oauth_token.token_type)
        self.assertEqual('email:read challenge:read challenge:write', player.oauth_token.scope)
        self.assertEqual('testuser', player.oauth_token.account_username)
        self.assertEqual('testuser@example.com', player.oauth_token.account_email)

    def test_existing_user(self, *args):
        created_player = Player.objects.create(lichess_username='testuser')
        created_player.profile = {}
        created_player.save()
        User.objects.create(username='testuser')

        response = self.client.get(reverse('lichess_auth'), self.auth_params, follow=True)

        self.assertRedirects(response, league_url('team', 'user_dashboard'))
        self.assertContains(response, '<h3>testuser</h3>', status_code=200)

        player = Player.objects.get(lichess_username='testuser')
        # The existing player already has a profile field, so it shouldn't have been re-fetched
        self.assertIsNone(player.rating_for(get_league('team')))
        self.assertIsNone(player.games_played_for(get_league('team')))

    @patch('heltour.tournament.oauth._decode_state',
           return_value={'league': league_tag('team'), 'token': '999'})
    def test_slack_link(self, *args):
        LoginToken.objects.create(secret_token='999', slack_user_id='U1234')

        response = self.client.get(reverse('lichess_auth'), self.auth_params, follow=True)

        self.assertRedirects(response, league_url('team', 'user_dashboard'))
        self.assertContains(response, '<h3>testuser</h3>', status_code=200)

        player = Player.objects.get(lichess_username='testuser')
        self.assertEqual('U1234', player.slack_user_id)

    def test_session_redirect(self, *args):
        self.client.session['redirect_url'] = league_url('team', 'about')
        response = self.client.get(reverse('lichess_auth'), self.auth_params)
        self.assertRedirects(response, league_url('team', 'about'))
